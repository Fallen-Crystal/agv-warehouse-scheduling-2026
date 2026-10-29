"""Safe Interval Path Planning for discrete unit-time moves and service holds.

A state is (cell, maximal safe time interval), with its earliest arrival label.
Earlier arrival dominates later arrival in the SAME interval: the robot can
wait safely until the later arrival. Reverse-edge reservations are still
checked at departure; continuous service must fit in the chosen interval.
"""

import heapq
from bisect import bisect_left
from collections import defaultdict

from agv.planning.astar import Router


class SafeIntervalRouter(Router):
    """Exact earliest-finish single-leg planner; no multi-agent optimality claim."""

    def leg(
        self,
        start,
        goal,
        time,
        vehicle,
        vertices,
        edges,
        service=0,
        service_blocked=None,
        delivery_station=None,
        not_before=None,
    ):
        self.stats["calls"] += 1
        service_blocked = set() if service_blocked is None else service_blocked
        strict = self.s.map_info.get("station_access") == "delivery_only"
        terminal = strict and goal in self.s.stations
        if terminal and delivery_station != goal:
            return None
        distances = self.distances(goal, vehicle)
        if start not in distances or (time, start) in vertices:
            return None
        horizon = self.search_limit(
            max(time, not_before or time), distances, vertices, edges, service, service_blocked
        )
        if hasattr(edges, "materialized"):
            edges = edges.materialized()
        if terminal and start == goal and not_before is not None and time < not_before:
            return None
        if hasattr(vertices, "timeline"):
            blocked = vertices.timeline()
        else:
            blocked = defaultdict(list)
            for t, p in vertices:
                blocked[p].append(t)
            blocked = {p: sorted(times) for p, times in blocked.items()}
        intervals = {}

        def safe_intervals(p):
            if p not in intervals:
                result, left = [], time
                times = blocked.get(p, ())
                for t in times[bisect_left(times, time) :]:
                    if t > horizon:
                        break
                    if left < t:
                        result.append((left, t - 1))
                    left = t + 1
                if left <= horizon:
                    result.append((left, horizon))
                intervals[p] = result
            return intervals[p]

        forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
        root_index = next(
            (i for i, (a, b) in enumerate(safe_intervals(start)) if a <= time <= b), None
        )
        if root_index is None:
            return None
        root = (start, root_index)
        arrivals, parents = {root: time}, {root: None}
        queue = [(time + distances[start], time, start, root_index)]
        self.stats["generated"] += 1
        best_goal = None
        best_finish = float("inf")
        while queue:
            estimate, arrival, p, index = heapq.heappop(queue)
            state = (p, index)
            if arrivals.get(state) != arrival:
                continue
            if estimate + service >= best_finish:
                break
            self.stats["expanded"] += 1
            _, upper = safe_intervals(p)[index]
            if p == goal:
                begin = max(arrival, not_before or arrival)
                while begin + service <= upper:
                    bad = next(
                        (t for t in range(begin, begin + service) if t in service_blocked), None
                    )
                    if bad is None:
                        if begin + service < best_finish:
                            best_finish = begin + service
                            best_goal = (state, begin)
                        break
                    if terminal:
                        break
                    begin = bad + 1
            if terminal and p == goal:
                continue
            # Moving out of a goal and returning via a later safe interval may
            # be necessary if its current interval cannot fit the service.
            for q in self.s.neighbors(p):
                if strict and q in self.s.stations and (q != goal or delivery_station != goal):
                    continue
                if q in forbidden or q not in distances:
                    continue
                for j, (lower, end) in enumerate(safe_intervals(q)):
                    enter = max(arrival + 1, lower)
                    latest = min(end, upper + 1, horizon - distances[q] - service)
                    if terminal and q == goal:
                        enter = max(enter, not_before or enter)
                        latest = min(latest, end - service)
                    if strict and p in self.s.stations:
                        latest = min(latest, arrival + 1)
                    while enter <= latest:
                        bad_service = (
                            terminal
                            and q == goal
                            and any(t in service_blocked for t in range(enter, enter + service))
                        )
                        if (enter - 1, q, p) not in edges and not bad_service:
                            break
                        enter += 1
                    if enter > latest:
                        continue
                    child = (q, j)
                    if enter >= arrivals.get(child, float("inf")):
                        continue
                    arrivals[child] = enter
                    parents[child] = (state, enter - 1)
                    heapq.heappush(queue, (enter + distances[q], enter, q, j))
                    self.stats["generated"] += 1
        if best_goal is None:
            return None
        state, begin = best_goal
        end_state = state
        chain = []
        while parents[state] is not None:
            previous, departure = parents[state]
            chain.append((state[0], arrivals[state], previous[0], departure))
            state = previous
        path = [start]
        for target, enter, source, departure in reversed(chain):
            path.extend([source] * (departure - (time + len(path) - 1)))
            path.append(target)
        path.extend([goal] * (begin - arrivals[end_state] + service))
        return path
