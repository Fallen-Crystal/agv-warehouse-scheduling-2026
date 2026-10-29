"""参考路径规划器：有等待动作和服务占位检查的时空 A*。"""

import heapq

from agv.planning.distance import DistanceOracle


class Router(DistanceOracle):
    def __init__(self, scenario):
        super().__init__(scenario)
        self.stats = dict(calls=0, expanded=0, generated=0)

    def search_limit(self, time, distances, vertices, edges, service, service_blocked):
        if self.s.horizon is not None:
            return self.s.horizon
        vertex_end = (
            vertices.end_time()
            if hasattr(vertices, "end_time")
            else max((t for t, _ in vertices), default=time)
        )
        edge_end = (
            edges.end_time()
            if hasattr(edges, "end_time")
            else max((t + 1 for t, _, _ in edges), default=time)
        )
        end = max([time, vertex_end, edge_end] + list(service_blocked))
        # After finite reservations expire, a simple static path suffices.
        return end + len(distances) + service + 1

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
        forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
        distances = self.distances(goal, vehicle)
        if start not in distances or (time, start) in vertices:
            return None
        limit = self.search_limit(
            max(time, not_before or time), distances, vertices, edges, service, service_blocked
        )
        if terminal and start == goal and not_before is not None and time < not_before:
            return None
        root = (start, time)
        parent = {root: None}
        queue = [(time + distances[start], time, start)]
        self.stats["generated"] += 1
        while queue:
            _, t, p = heapq.heappop(queue)
            self.stats["expanded"] += 1
            if (
                p == goal
                and t + service <= limit
                and (not_before is None or t >= not_before)
                and all((u, p) not in vertices for u in range(t, t + service + 1))
                and all(u not in service_blocked for u in range(t, t + service))
            ):
                path, state = [], (p, t)
                while state is not None:
                    path.append(state[0])
                    state = parent[state]
                return path[::-1] + [goal] * service
            if terminal and p == goal:
                continue
            if t >= limit:
                continue
            for q in (*self.s.neighbors(p), p):
                if (
                    strict
                    and q in self.s.stations
                    and (
                        q != goal
                        or delivery_station != goal
                        or (not_before is not None and t + 1 < not_before)
                    )
                ):
                    continue
                if strict and p in self.s.stations and q == p:
                    continue
                state = (q, t + 1)
                if q in forbidden or q not in distances or state in parent:
                    continue
                if (t + 1, q) in vertices or (t, q, p) in edges:
                    continue
                if t + 1 + distances[q] + service > limit:
                    continue
                parent[state] = (p, t)
                heapq.heappush(queue, (t + 1 + distances[q], t + 1, q))
                self.stats["generated"] += 1
        return None
