"""Discrete mixed-flow kernel using the existing SIPP routing implementation.

Stock is changed at physical pickup/putaway completion, never at publication.
Every committed trip includes an interruptible fallback home path. Stream idle
holds preserve all peer reservations; terminal and work cells cannot be held.
"""

from agv.rules.wepa import dispatchable, eligible_slot, validate_trip
from agv.world.reservations import ReservationTable
from agv.world.transit import advance_fleet


class World:
    def __init__(self, model, *, router):
        self.model = model
        self.scene = model["scene"]
        self.router = router
        self.tasks = {j["id"]: dict(j) for j in model["tasks"]}
        self.slots = model["slots"]
        self.stock = set(model["occupied"])
        self.out_reserved, self.in_reserved = {}, {}
        self.bound, self.visible = {}, {}
        self.plans = [[p] for p in self.scene.homes[: model["vehicles"]]]
        self.history = [[p] for p in self.scene.homes[: model["vehicles"]]]
        self.labels = [[] for _ in self.plans]
        self.active = [None for _ in self.plans]
        self.records, self.completed, self.assigned = [], set(), set()
        self.processed_pickups = set()
        self.locks = {}
        self.time, self.closed = 0, False
        self.decisions, self.holds = [], 0
        self.routing_failures = 0
        self.past_moves = 0

    def table(self):
        return ReservationTable(self.plans, self.time)

    def record_routing_failure(self):
        self.routing_failures += 1

    def ordinary(self, p):
        return (
            p in self.scene.transit_only
            and p not in self.scene.homes
            and p not in self.scene.stations
            and p not in self.scene.pickup_zones
            and self.scene.free(p)
        )

    def publish_and_complete(self):
        t = self.time
        for record in self.records:
            j, sid = self.tasks[record["task"]], record["slot"]
            if (
                j["kind"] == "retrieval"
                and record["pickup_end"] <= t
                and j["id"] not in self.processed_pickups
            ):
                if sid not in self.stock or self.out_reserved.get(sid) != j["id"]:
                    raise ValueError("Stock pickup without an exclusive reservation")
                self.stock.remove(sid)
                del self.out_reserved[sid]
                self.processed_pickups.add(j["id"])
            if record["end"] <= t and j["id"] not in self.completed:
                if j["kind"] == "delivery":
                    if sid in self.stock or self.in_reserved.get(sid) != j["id"]:
                        raise ValueError("Putaway exceeds physical slot capacity")
                    self.stock.add(sid)
                    del self.in_reserved[sid]
                self.completed.add(j["id"])
                self.active[record["vehicle"]] = None
        for j in self.tasks.values():
            if j["release"] <= t:
                self.visible[j["id"]] = j
        self.closed = t >= self.model["close_at"]
        # WMS allocation is deterministic and independent of vehicle selection.
        for j in sorted(self.visible.values(), key=lambda j: (j["release"], j["id"])):
            if j["id"] in self.bound:
                continue
            sid = eligible_slot(self.slots, self.stock, self.out_reserved, self.in_reserved, j)
            if sid is not None:
                self.bound[j["id"]] = sid
                reservation = self.out_reserved if j["kind"] == "retrieval" else self.in_reserved
                reservation[sid] = j["id"]

    def ready(self):
        return [
            j
            for j in self.visible.values()
            if j["id"] not in self.assigned
            and j["id"] in self.bound
            and dispatchable(
                self.slots,
                self.stock,
                self.in_reserved,
                self.locks,
                self.bound[j["id"]],
                j,
                self.time,
            )
        ]

    def endpoints(self, j):
        slot = self.slots[self.bound[j["id"]]]
        if j["kind"] == "delivery":
            return [(j["port"], p, 1, 2 * slot["level"]) for p in slot["points"]]
        return [(p, j["port"], 2 * slot["level"], 1) for p in slot["points"]]

    def estimate(self, vehicle, j):
        return min(
            self.router.distance(self.plans[vehicle][0], a, vehicle)
            + ps
            + self.router.distance(a, b, vehicle)
            + ds
            for a, b, ps, ds in self.endpoints(j)
        )

    def trip(self, vehicle, j):
        vertices, edges = self.table().view_excluding(vehicle, self.time)
        best = None
        for pickup, drop, ps, ds in self.endpoints(j):
            path, now, start = [], self.time, self.plans[vehicle][0]
            stamps = []
            for goal, service in ((pickup, ps), (drop, ds), (self.scene.homes[vehicle], 0)):
                leg = self.router.leg(
                    start,
                    goal,
                    now,
                    vehicle,
                    vertices,
                    edges,
                    service=service,
                    delivery_station=goal if goal in self.scene.stations else None,
                )
                if leg is None:
                    break
                arrival = now + len(leg) - 1 - service
                now += len(leg) - 1
                path.extend(leg if not path else leg[1:])
                stamps.append((arrival, now))
                start = goal
            else:
                record = dict(
                    task=j["id"],
                    vehicle=vehicle,
                    slot=self.bound[j["id"]],
                    assigned_at=self.time,
                    pickup=pickup,
                    drop=drop,
                    pickup_arrival=stamps[0][0],
                    pickup_end=stamps[0][1],
                    drop_arrival=stamps[1][0],
                    end=stamps[1][1],
                )
                moves = sum(a != b for a, b in zip(path, path[1:]))
                key = (record["end"], moves, pickup, drop)
                if best is None or key < best[0]:
                    best = key, path, record
        return None if best is None else best[1:]

    def commit(self, vehicle, j, proposal):
        if type(vehicle) is not int or not 0 <= vehicle < len(self.plans):
            raise ValueError("Unknown vehicle")
        path, record = proposal
        if self.active[vehicle] is not None or j["id"] in self.assigned:
            raise ValueError("Busy vehicle or duplicate task")
        if j not in self.ready():
            raise ValueError("Task no longer dispatchable")
        validate_trip(
            self.scene,
            self.slots[self.bound[j["id"]]],
            j,
            vehicle,
            self.time,
            self.plans[vehicle][0],
            path,
            record,
        )
        if self.table().conflict(path, self.time, vehicle):
            raise ValueError("Proposed suffix conflicts with reservations")
        self.plans[vehicle] = path
        self.records.append(record)
        self.active[vehicle] = record
        self.assigned.add(j["id"])
        bay = self.slots[record["slot"]]["bay"]
        self.locks[bay] = record["pickup_end"] if j["kind"] == "retrieval" else record["end"]

    def advance(self):
        held_vehicles = set()
        table = None
        if not (self.closed and len(self.completed) == len(self.tasks)):
            for k, plan in enumerate(self.plans):
                if self.active[k] is None and len(plan) > 1 and self.ordinary(plan[0]):
                    held = [plan[0]] + plan
                    if table is None:
                        table = self.table()
                    if table.conflict(held, self.time, k) is None:
                        self.plans[k] = held
                        table.hold(k, self.time, 1)
                        self.holds += 1
                        held_vehicles.add(k)

        def state_at(k):
            plan = self.plans[k]
            r = self.active[k]
            state = "standby" if r is None else "empty"
            if r is not None:
                if r["pickup_arrival"] <= self.time < r["pickup_end"]:
                    state = "service"
                elif r["pickup_end"] <= self.time < r["drop_arrival"]:
                    state = "loaded"
                elif r["drop_arrival"] <= self.time < r["end"]:
                    state = "service"
            elif len(plan) > 1 and k not in held_vehicles:
                state = "empty"
            return state

        self.time, moves = advance_fleet(self.plans, self.history, self.labels, state_at, self.time)
        self.past_moves += moves

    @property
    def done(self):
        return (
            self.closed
            and len(self.completed) == len(self.tasks)
            and all(len(p) == 1 and p[0] == self.scene.homes[k] for k, p in enumerate(self.plans))
        )

    def surrogate(self):
        # Uses only published jobs and actual completed history. No full-stream
        # reference denominators, future counts, releases or closure time.
        visible = list(self.visible.values())
        n = max(1, len(visible))
        estimates = {r["task"]: r["end"] for r in self.records}
        available = [r["end"] if r else self.time for r in self.active]
        for j in visible:
            if j["id"] in estimates:
                continue
            if j["id"] in self.bound:
                options = [
                    (max(self.time, available[k]) + self.estimate(k, j), k)
                    for k in range(len(self.plans))
                ]
                end, k = min(options)
                available[k] = end
            else:
                end = max(available) + self.scene.width + self.scene.height
            estimates[j["id"]] = end
        scale = self.scene.width + self.scene.height
        moves = self.past_moves + sum(sum(a != b for a, b in zip(p, p[1:])) for p in self.plans)
        return (
            0.5 * max(estimates.values(), default=self.time) / scale
            + 0.3 * sum(estimates[j["id"]] - j["release"] for j in visible) / (n * scale)
            + 0.2 * moves / (n * scale)
        )
