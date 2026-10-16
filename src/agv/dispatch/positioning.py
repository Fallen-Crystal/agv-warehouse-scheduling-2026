"""Visible-history positioning, with static corridor exclusions and hysteresis."""

from collections import Counter
from math import exp

from agv.dispatch.assignment import minimum_assignment
from agv.domain import Scenario
from agv.planning.astar import Router


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
        self, observation, *, strength=32.0, sigma=18.0, interval=10, capacity=2, hysteresis=3.0
    ):
        self.scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
        self.router = Router(self.scenario)
        self.candidates = waiting_candidates(self.scenario)
        self.candidate_set = set(self.candidates)
        self.strength, self.sigma = strength, sigma
        self.interval, self.capacity, self.hysteresis = interval, capacity, hysteresis
        self.history, self.last = {}, -interval
        self.log = []
        self.available = {v["id"] for v in observation["vehicles"] if v["available"]}
        self.new_idle = set()

    def observe(self, observation):
        available = {v["id"] for v in observation["vehicles"] if v["available"]}
        self.new_idle.update(available - self.available)
        self.available = available
        for job in observation["pending"] + [
            v["active_task"] for v in observation["vehicles"] if v["active_task"]
        ]:
            if job["id"] not in self.history:
                # Both single-row sides retain the one inventory identity.
                from agv.dispatch.shadow import _task

                task = _task(job)
                self.history[job["id"]] = (
                    task.release,
                    tuple(self.scenario.pickup_candidates(task)),
                )

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

        zones = {i: [] for i in range(len(self.scenario.stations))}
        for point in self.candidates:
            zone = min(
                zones,
                key=lambda i: (
                    abs(point[0] - self.scenario.stations[i][0])
                    + abs(point[1] - self.scenario.stations[i][1]),
                    i,
                ),
            )
            zones[zone].append(point)
        targets = []
        for points in zones.values():
            # Capacity is hard: at most c shared target slots per station zone.
            old_points = [
                tuple(t["target"])
                for t in observation.get("positioning_targets", [])
                if t is not None and tuple(t["target"]) in points
            ]
            ordered = sorted(
                points,
                key=lambda p: (min(distance(v, p) for v in vehicles) - self.strength * score(p), p),
            )
            targets.extend(list(dict.fromkeys(old_points + ordered))[: self.capacity])
        targets += list(self.scenario.homes)
        targets = list(dict.fromkeys(targets))
        costs = []
        for vehicle in vehicles:
            k, current = vehicle["id"], tuple(vehicle["position"])
            old = observation.get("positioning_targets", [None] * len(self.scenario.homes))[k]
            old_point = tuple(old["target"]) if old else current
            row = []
            for target in targets:
                if target in self.scenario.homes and target != self.scenario.homes[k]:
                    row.append(float("inf"))
                    continue
                penalty = 0 if target == old_point else self.hysteresis
                row.append(distance(vehicle, target) - self.strength * score(target) + penalty)
            costs.append(row)
        choice = minimum_assignment(costs)
        result = []

        def zone(point):
            return min(
                zones,
                key=lambda i: (
                    abs(point[0] - self.scenario.stations[i][0])
                    + abs(point[1] - self.scenario.stations[i][1]),
                    i,
                ),
            )

        current_targets = observation.get("positioning_targets", [])
        counts = Counter(zone(tuple(t["target"])) for t in current_targets if t is not None)
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
                old_zone = zone(old_point) if old else None
                new_zone = zone(target) if target not in self.scenario.homes else None
                if (
                    new_zone is not None
                    and new_zone != old_zone
                    and counts[new_zone] >= self.capacity
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
                and counts[zone(current)] < self.capacity
            ):
                counts[zone(current)] += 1
                result.append((v["id"], current))
        return result
