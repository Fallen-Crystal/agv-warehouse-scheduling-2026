"""Static distances, including own-home and terminal-station permissions."""

from collections import deque


class DistanceOracle:
    def __init__(self, scenario):
        self.s = scenario
        self.cache = {}

    def distances(self, goal, vehicle):
        key = (goal, vehicle)
        if key not in self.cache:
            forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
            seen, queue = {goal: 0}, deque([goal])
            while queue:
                p = queue.popleft()
                if (
                    self.s.map_info.get("station_access") == "delivery_only"
                    and p in self.s.stations
                    and p != goal
                ):
                    continue
                for q in self.s.neighbors(p):
                    if q not in forbidden and q not in seen:
                        seen[q] = seen[p] + 1
                        queue.append(q)
            self.cache[key] = seen
        return self.cache[key]

    def distance(self, start, goal, vehicle):
        return self.distances(goal, vehicle).get(start, float("inf"))
