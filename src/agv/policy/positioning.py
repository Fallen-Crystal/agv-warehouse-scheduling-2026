"""Visible-history positioning, with static corridor exclusions and hysteresis."""

from collections import Counter, deque
from math import exp, isfinite

from agv.planning.astar import Router
from agv.policy.assignment import minimum_assignment
from agv.warehouse.scenarios import Scenario


def articulation_points(graph):
    """Iterative Tarjan DFS; warehouse graphs can exceed Python recursion depth."""
    number, low, parent, children, cuts = {}, {}, {}, Counter(), set()
    for root in graph:
        if root in number:
            continue
        number[root] = low[root] = len(number)
        stack = [(root, iter(graph[root]))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                stack.pop()
                if node in parent:
                    p = parent[node]
                    low[p] = min(low[p], low[node])
                    if p in parent and low[node] >= number[p]:
                        cuts.add(p)
                elif children[node] > 1:
                    cuts.add(node)
                continue
            if neighbor not in number:
                parent[neighbor] = node
                children[node] += 1
                number[neighbor] = low[neighbor] = len(number)
                stack.append((neighbor, iter(graph[neighbor])))
            elif parent.get(node) != neighbor:
                low[node] = min(low[node], number[neighbor])
    return cuts


def waiting_candidates(scenario):
    cells = {
        (x, y)
        for x in range(scenario.width)
        for y in range(scenario.height)
        if scenario.free((x, y))
        and (x, y) not in scenario.homes
        and (x, y) not in scenario.stations
    }
    graph = {p: tuple(q for q in scenario.neighbors(p) if q in cells) for p in sorted(cells)}
    cuts = articulation_points(graph)
    service = set(scenario.pickup_zones) | set(scenario.stations)
    return tuple(
        p
        for p in sorted(scenario.transit_only)
        if p in graph
        and p not in cuts
        and len(graph[p]) > 2
        and all(q not in service for q in scenario.neighbors(p))
    )


class PositioningPolicy:
    """No release oracle: history consists only of orders actually observed."""

    def __init__(
        self,
        observation,
        *,
        strength=32.0,
        sigma=18.0,
        interval=10,
        capacity=2,
        hysteresis=3.0,
        stat_window=None,
        rebalance_period=None,
        hotspot_zones=0,
        protect_utilization=None,
    ):
        for name, value in (("interval", interval), ("capacity", capacity)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in (("stat_window", stat_window), ("rebalance_period", rebalance_period)):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        for name, value in (("strength", strength), ("sigma", sigma), ("hysteresis", hysteresis)):
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not sigma:
            raise ValueError("sigma must be positive")
        if type(hotspot_zones) is not int or hotspot_zones < 0:
            raise ValueError("hotspot_zones must be a nonnegative integer")
        if protect_utilization is not None and (
            type(protect_utilization) not in (int, float)
            or not isfinite(protect_utilization)
            or not 0 < protect_utilization <= 1
        ):
            raise ValueError("protect_utilization must be in (0, 1] or None")
        self.scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
        self.router = Router(self.scenario)
        self.candidates = waiting_candidates(self.scenario)
        self.candidate_set = set(self.candidates)
        self.strength, self.sigma = strength, sigma
        self.interval = interval if rebalance_period is None else rebalance_period
        self.capacity, self.hysteresis = capacity, hysteresis
        self.stat_window, self.rebalance_period = stat_window, rebalance_period
        self.hotspot_zones, self.protect_utilization = hotspot_zones, protect_utilization
        self.history, self.last = {}, -self.interval
        self.occupancy = deque()
        self.zones = {i: [] for i in range(len(self.scenario.stations))}
        for point in self.candidates:
            self.zones[self._zone(point)].append(point)
        self.log = []
        self.available = {v["id"] for v in observation["vehicles"] if v["available"]}
        self.new_idle = set()

    def _zone(self, point):
        return min(
            self.zones,
            key=lambda i: (
                abs(point[0] - self.scenario.stations[i][0])
                + abs(point[1] - self.scenario.stations[i][1]),
                i,
            ),
        )

    def _utilization(self, zone, now, capacity):
        if not self.occupancy or now <= self.occupancy[0][0]:
            return 0.0
        start = max(self.occupancy[0][0], now - (self.stat_window or 200))
        occupied = 0
        samples = list(self.occupancy)
        for i, (time, zones) in enumerate(samples):
            end = samples[i + 1][0] if i + 1 < len(samples) else now
            occupied += zones[zone] * max(0, end - max(time, start))
        return min(1.0, occupied / ((now - start) * capacity))

    def observe(self, observation):
        now = observation["time"]
        available = {v["id"] for v in observation["vehicles"] if v["available"]}
        self.new_idle.update(available - self.available)
        self.available = available
        for job in observation["pending"] + [
            v["active_task"] for v in observation["vehicles"] if v["active_task"]
        ]:
            if job["id"] not in self.history:
                # Both single-row sides retain the one inventory identity.
                from agv.policy.forecast import _task

                task = _task(job)
                if task.release > now:
                    continue
                self.history[job["id"]] = (
                    task.release,
                    tuple(self.scenario.pickup_candidates(task)),
                )
        if self.stat_window is not None:
            self.history = {
                key: value
                for key, value in self.history.items()
                if value[0] >= now - self.stat_window
            }
        if self.protect_utilization is not None:
            targets = observation.get("positioning_targets", [])
            occupied = Counter(
                self._zone(tuple(targets[v["id"]]["target"]))
                for v in observation["vehicles"]
                if v["available"]
                and v["id"] < len(targets)
                and targets[v["id"]] is not None
                and tuple(v["position"]) == tuple(targets[v["id"]]["target"])
                and tuple(v["position"]) in self.candidate_set
            )
            if self.occupancy and self.occupancy[-1][0] == now:
                self.occupancy[-1] = (now, occupied)
            else:
                self.occupancy.append((now, occupied))
            cutoff = now - (self.stat_window or 200)
            while len(self.occupancy) > 1 and self.occupancy[1][0] <= cutoff:
                self.occupancy.popleft()

    def action(self, observation):
        self.observe(observation)
        now = observation["time"]
        # Closed means no new demand; preserve safe fallbacks and let final return happen.
        if (
            observation["order_stream_closed"]
            or (now - self.last < self.interval and not self.new_idle)
            or any(j.get("dispatchable", True) for j in observation["pending"])
            or not self.history
        ):
            return []
        self.last = now
        self.new_idle.clear()
        heat = Counter()
        for released, points in self.history.values():
            for point in points:
                heat[point] += exp(-(now - released) / 200.0) / len(points)
        mass = sum(heat.values())
        if mass < 0.01:
            return []
        vehicles = [v for v in observation["vehicles"] if v["available"]]
        if not vehicles:
            return []
        if len(self.router.cache) > 64:
            self.router.cache.clear()
        distances = {
            v["id"]: self.router.distances(tuple(v["position"]), v["id"]) for v in vehicles
        }

        def distance(vehicle, point):
            return distances[vehicle["id"]].get(point, float("inf"))

        # Scores use static geometry and historical pickup demand, not unseen orders.
        scores = {}

        def score(point):
            if point in scores:
                return scores[point]
            scores[point] = (
                sum(
                    h * exp(-(abs(point[0] - p[0]) + abs(point[1] - p[1])) / self.sigma)
                    for p, h in heat.items()
                )
                / mass
            )
            return scores[point]

        # Keep precomputed geometry, but allow callers/tests to narrow candidate points.
        candidates = set(self.candidates)
        zones = {
            i: [point for point in points if point in candidates]
            for i, points in self.zones.items()
        }
        zone_heat = Counter()
        for point, value in heat.items():
            zone_heat[self._zone(point)] += value
        hot = set(sorted(zone_heat, key=lambda z: (-zone_heat[z], z))[: self.hotspot_zones])
        capacities = {i: self.capacity + (i in hot) for i in zones}
        targets = []
        for zone_id, points in zones.items():
            # Each zone exposes only its configured safe target slots.
            old_points = [
                tuple(t["target"])
                for t in observation.get("positioning_targets", [])
                if t is not None and tuple(t["target"]) in points
            ]
            ordered = sorted(
                points,
                key=lambda p: (min(distance(v, p) for v in vehicles) - self.strength * score(p), p),
            )
            targets.extend(list(dict.fromkeys(old_points + ordered))[: capacities[zone_id]])
        targets += list(self.scenario.homes)
        targets = list(dict.fromkeys(targets))
        current_targets = observation.get("positioning_targets", [])
        counts = Counter(self._zone(tuple(t["target"])) for t in current_targets if t is not None)
        costs = []
        for vehicle in vehicles:
            k, current = vehicle["id"], tuple(vehicle["position"])
            old = observation.get("positioning_targets", [None] * len(self.scenario.homes))[k]
            old_point = tuple(old["target"]) if old else current
            # Never protect an unsafe point, an in-flight car or an overfull zone.
            protected = (
                self.protect_utilization is not None
                and old is not None
                and current == old_point
                and current in self.candidate_set
                and counts[self._zone(current)] <= capacities[self._zone(current)]
                and self._utilization(self._zone(current), now, capacities[self._zone(current)])
                > self.protect_utilization
            )
            row = []
            for target in targets:
                if target in self.scenario.homes and target != self.scenario.homes[k]:
                    row.append(float("inf"))
                    continue
                # Protection affects voluntary relocation only; the command gate can still
                # reject a hold and move this car along its reserved fallback to clear traffic.
                if protected and target != old_point:
                    row.append(float("inf"))
                    continue
                penalty = 0 if target == old_point else self.hysteresis
                row.append(distance(vehicle, target) - self.strength * score(target) + penalty)
            costs.append(row)
        choice = minimum_assignment(costs)
        result = []

        for i, selected in enumerate(choice):
            if selected is None:
                continue
            v, target = vehicles[i], targets[selected]
            current = tuple(v["position"])
            old = observation.get("positioning_targets", [None] * len(self.scenario.homes))[v["id"]]
            old_point = tuple(old["target"]) if old else current
            stay = distance(v, old_point) - self.strength * score(old_point)
            valid_stay = (
                old_point in self.candidate_set or old_point == self.scenario.homes[v["id"]]
            )
            register = old is None and target == current and current in self.candidate_set
            if register or (
                target != old_point and (not valid_stay or costs[i][selected] < stay - 1e-9)
            ):
                old_zone = self._zone(old_point) if old else None
                new_zone = self._zone(target) if target not in self.scenario.homes else None
                if (
                    new_zone is not None
                    and new_zone != old_zone
                    and counts[new_zone] >= capacities[new_zone]
                ):
                    continue
                if old_zone is not None:
                    counts[old_zone] -= 1
                if new_zone is not None:
                    counts[new_zone] += 1
                result.append((v["id"], target))
            elif (
                old is None
                and current in self.candidate_set
                and counts[self._zone(current)] < capacities[self._zone(current)]
            ):
                counts[self._zone(current)] += 1
                result.append((v["id"], current))
        return result
