"""Discrete mixed-flow kernel using the existing SIPP routing implementation.

Stock is changed at physical pickup/putaway completion, never at publication.
Every committed trip includes an interruptible fallback home path. Stream idle
holds preserve all peer reservations; terminal and work cells cannot be held.
"""
from copy import deepcopy
from math import ceil

from agv.planning.sipp import SafeIntervalRouter
from agv.world.reservations import ReservationTable


class World:
    def __init__(self, model):
        self.model = model
        self.scene = model["scene"]
        self.router = SafeIntervalRouter(self.scene)
        self.tasks = {j["id"]: dict(j) for j in model["tasks"]}
        self.slots = model["slots"]
        self.stock = set(model["occupied"])
        self.out_reserved, self.in_reserved = {}, {}
        self.bound, self.visible = {}, {}
        self.plans = [[p] for p in self.scene.homes[:model["vehicles"]]]
        self.history = [[p] for p in self.scene.homes[:model["vehicles"]]]
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

    def ordinary(self, p):
        return (p in self.scene.transit_only and p not in self.scene.homes
                and p not in self.scene.stations and p not in self.scene.pickup_zones
                and self.scene.free(p))

    def publish_and_complete(self):
        t = self.time
        for record in self.records:
            j, sid = self.tasks[record["task"]], record["slot"]
            if j["kind"] == "retrieval" and record["pickup_end"] <= t and j["id"] not in self.processed_pickups:
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
            if j["kind"] == "retrieval":
                inbound_bays = {self.slots[s]["bay"] for s in self.in_reserved}
                eligible = [s for s in self.slots if s["sku"] == j["sku"]
                            and s["id"] in self.stock and s["id"] not in self.out_reserved
                            and s["bay"] not in inbound_bays]
                eligible.sort(key=lambda s: (s["bay"], -s["level"]))
                reservation = self.out_reserved
            else:
                outbound_bays = {self.slots[s]["bay"] for s in self.out_reserved}
                eligible = [s for s in self.slots if s["sku"] == j["sku"]
                            and s["id"] not in self.stock and s["id"] not in self.in_reserved
                            and s["bay"] not in outbound_bays]
                eligible.sort(key=lambda s: (s["bay"], s["level"]))
                reservation = self.in_reserved
            if eligible:
                sid = eligible[0]["id"]
                self.bound[j["id"]] = sid
                reservation[sid] = j["id"]

    def ready(self):
        jobs = []
        for j in self.visible.values():
            jid = j["id"]
            if jid in self.assigned or jid not in self.bound:
                continue
            s = self.slots[self.bound[jid]]
            if self.locks.get(s["bay"], 0) > self.time:
                continue
            if j["kind"] == "retrieval":
                if any(q["bay"] == s["bay"] and q["level"] > s["level"]
                       and q["id"] in self.stock for q in self.slots):
                    continue
            elif any(q["bay"] == s["bay"] and q["level"] < s["level"]
                     and q["id"] in self.in_reserved for q in self.slots):
                continue
            jobs.append(j)
        return jobs

    def endpoints(self, j):
        slot = self.slots[self.bound[j["id"]]]
        if j["kind"] == "delivery":
            return [(j["port"], p, 1, 2 * slot["level"]) for p in slot["points"]]
        return [(p, j["port"], 2 * slot["level"], 1) for p in slot["points"]]

    def estimate(self, vehicle, j):
        return min(self.router.distance(self.plans[vehicle][0], a, vehicle)
                   + ps + self.router.distance(a, b, vehicle) + ds
                   for a, b, ps, ds in self.endpoints(j))

    def trip(self, vehicle, j):
        vertices, edges = self.table().view_excluding(vehicle, self.time)
        best = None
        for pickup, drop, ps, ds in self.endpoints(j):
            path, now, start = [], self.time, self.plans[vehicle][0]
            stamps = []
            for goal, service in ((pickup, ps), (drop, ds), (self.scene.homes[vehicle], 0)):
                leg = self.router.leg(start, goal, now, vehicle, vertices, edges,
                    service=service, delivery_station=goal if goal in self.scene.stations else None)
                if leg is None:
                    break
                arrival = now + len(leg) - 1 - service
                now += len(leg) - 1
                path.extend(leg if not path else leg[1:])
                stamps.append((arrival, now))
                start = goal
            else:
                record = dict(task=j["id"], vehicle=vehicle, slot=self.bound[j["id"]],
                    assigned_at=self.time, pickup=pickup, drop=drop,
                    pickup_arrival=stamps[0][0], pickup_end=stamps[0][1],
                    drop_arrival=stamps[1][0], end=stamps[1][1])
                moves = sum(a != b for a, b in zip(path, path[1:]))
                key = (record["end"], moves, pickup, drop)
                if best is None or key < best[0]:
                    best = key, path, record
        return None if best is None else best[1:]

    def commit(self, vehicle, j, proposal):
        path, record = proposal
        if self.active[vehicle] is not None or j["id"] in self.assigned:
            raise ValueError("Busy vehicle or duplicate task")
        if j not in self.ready():
            raise ValueError("Task no longer dispatchable")
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
        if not (self.closed and len(self.completed) == len(self.tasks)):
            for k, plan in enumerate(self.plans):
                if self.active[k] is None and len(plan) > 1 and self.ordinary(plan[0]):
                    held = [plan[0]] + plan
                    if self.table().conflict(held, self.time, k) is None:
                        self.plans[k] = held
                        self.holds += 1
                        held_vehicles.add(k)
        for k, plan in enumerate(self.plans):
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
            following = plan[1] if len(plan) > 1 else plan[0]
            self.past_moves += following != plan[0]
            self.history[k].append(following)
            self.labels[k].append(state)
            if len(plan) > 1:
                self.plans[k] = plan[1:]
        self.time += 1

    @property
    def done(self):
        return (self.closed and len(self.completed) == len(self.tasks)
                and all(len(p) == 1 and p[0] == self.scene.homes[k]
                        for k, p in enumerate(self.plans)))

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
                options = [(max(self.time, available[k]) + self.estimate(k, j), k)
                           for k in range(len(self.plans))]
                end, k = min(options)
                available[k] = end
            else:
                end = max(available) + self.scene.width + self.scene.height
            estimates[j["id"]] = end
        scale = self.scene.width + self.scene.height
        moves = self.past_moves + sum(sum(a != b for a, b in zip(p, p[1:])) for p in self.plans)
        return (.5 * max(estimates.values(), default=self.time) / scale
                + .3 * sum(estimates[j["id"]] - j["release"] for j in visible) / (n * scale)
                + .2 * moves / (n * scale))


def batch(world, rule):
    assignments = []
    for _ in range(len(world.plans)):
        cars = [k for k, r in enumerate(world.active) if r is None]
        jobs = world.ready()
        if not cars or not jobs:
            break
        estimates = {(k, j["id"]): world.estimate(k, j) for k in cars for j in jobs}
        if rule == "eta":
            choices = sorted((estimates[k, j["id"]], j["release"], j["id"], k, j)
                             for k in cars for j in jobs)
        else:
            def priority(j):
                service = min(ps + ds for _, _, ps, ds in world.endpoints(j))
                if rule == "inbound":
                    return (j["kind"] != "delivery", j["release"], j["id"])
                if rule == "outbound":
                    return (j["kind"] != "retrieval", j["release"], j["id"])
                if rule == "short":
                    return (min(estimates[k, j["id"]] for k in cars), service, j["id"])
                if rule == "long":
                    return (-min(estimates[k, j["id"]] for k in cars), j["release"], j["id"])
                return (j["release"], j["id"])
            ordered = sorted(jobs, key=priority)
            choices = [(estimates[k, j["id"]], j["release"], j["id"], k, j)
                       for j in ordered for k in sorted(cars, key=lambda k: estimates[k, j["id"]])]
        committed = False
        for _, _, _, k, j in choices:
            proposal = world.trip(k, j)
            if proposal is None:
                world.routing_failures += 1
                continue
            world.commit(k, j, proposal)
            assignments.append((k, j["id"]))
            committed = True
            break
        if not committed:
            break
    return assignments


def decide(world, method):
    if method != "joint":
        return batch(world, method)
    best = None
    # Real SIPP previews for six assignment/priority combinations, same world.
    for rule in ("fcfs", "eta", "short", "long", "inbound", "outbound"):
        trial = deepcopy(world)
        pairs = batch(trial, rule)
        if not pairs:
            continue
        key = (trial.surrogate(), rule)
        if best is None or key < best[0]:
            best = key, trial, pairs
    if best is None:
        return []
    trial, pairs = best[1:]
    # Commit the previewed state atomically; trace checker verifies all effects.
    for field in ("plans", "records", "active", "assigned", "locks"):
        setattr(world, field, getattr(trial, field))
    return pairs


def run(model, method="hybrid", max_time=None, *, seed=0, previews=6):
    from wepa.search import METHODS, SearchPolicy
    if method not in ("fcfs", "eta", "joint") + METHODS:
        raise ValueError("Unknown mixed-flow method")
    policy = SearchPolicy(method, seed=seed, previews=previews) if method in METHODS else None
    w = World(model)
    limit = max_time or model["close_at"] + max(3000, len(model["tasks"]) * 150)
    while w.time <= limit:
        w.publish_and_complete()
        if w.done:
            break
        if any(r is None for r in w.active) and w.ready():
            pairs = policy.action(w) if policy is not None else decide(w, method)
            if pairs:
                w.decisions.append(dict(time=w.time, pairs=pairs,
                    visible_ids=sorted(w.visible)))
        w.advance()
    valid = w.done
    jobs = w.tasks
    flows = sorted(r["end"] - jobs[r["task"]]["release"] for r in w.records)
    moves = sum(a != b for p in w.history for a, b in zip(p, p[1:]))
    empty = sum(a != b and label != "loaded" for p, labels in zip(w.history, w.labels)
                for a, b, label in zip(p, p[1:], labels))
    by_kind = {}
    for kind in ("delivery", "retrieval"):
        records = [r for r in w.records if jobs[r["task"]]["kind"] == kind]
        values = sorted(r["end"] - jobs[r["task"]]["release"] for r in records)
        by_kind[kind] = dict(count=len(values), mean_flow=sum(values) / len(values) if values else 0,
            p90=values[ceil(.9 * len(values)) - 1] if values else 0)
    return dict(valid=valid, method=method, time=w.time, paths=w.history, labels=w.labels,
        records=w.records, completed=sorted(w.completed), decisions=w.decisions,
        T=max((r["end"] for r in w.records), default=0),
        R=sum(flows) / len(flows) if flows else 0, D=moves, empty_distance=empty,
        traffic_wait=sum(a == b and label in ("empty", "loaded")
            for p, labels in zip(w.history, w.labels) for a, b, label in zip(p, p[1:], labels)),
        p90=flows[ceil(.9 * len(flows)) - 1] if flows else 0, by_kind=by_kind,
        holds=w.holds, routing_failures=w.routing_failures,
        final_stock=sorted(w.stock), search_log=policy.logs if policy is not None else [])
