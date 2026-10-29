"""Static distances, including own-home and terminal-station permissions."""

from collections import OrderedDict, deque
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType


class _DistanceTable(Mapping):
    """Read-only static values may be shared by independent world snapshots."""

    def __init__(self, values):
        self._values = MappingProxyType(values)

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __deepcopy__(self, memo):
        return self


def geometry_key(scenario):
    """Only immutable inputs that affect routing; never include future orders."""
    return (
        scenario.width,
        scenario.height,
        frozenset(scenario.blocked),
        tuple(scenario.homes),
        tuple(scenario.stations),
        scenario.map_info.get("station_access") == "delivery_only",
        scenario.horizon,
    )


@lru_cache(maxsize=128)
def _distances(geometry, goal, vehicle):
    width, height, blocked, homes, stations, strict, _ = geometry
    forbidden = set(homes) - {homes[vehicle]}
    seen, queue = {goal: 0}, deque([goal])
    while queue:
        p = queue.popleft()
        if strict and p in stations and p != goal:
            continue
        x, y = p
        for q in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
            if (
                0 <= q[0] < width
                and 0 <= q[1] < height
                and q not in blocked
                and q not in forbidden
                and q not in seen
            ):
                seen[q] = seen[p] + 1
                queue.append(q)
    return _DistanceTable(seen)


class DistanceOracle:
    def __init__(self, scenario):
        self.s = scenario
        self.geometry = geometry_key(scenario)
        self.cache = OrderedDict()

    def distances(self, goal, vehicle):
        key = (goal, vehicle)
        if key not in self.cache:
            self.cache[key] = _distances(self.geometry, goal, vehicle)
            if len(self.cache) > 64:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def distance(self, start, goal, vehicle):
        return self.distances(goal, vehicle).get(start, float("inf"))
