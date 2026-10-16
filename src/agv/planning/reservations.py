"""Mutable vertex reservations with an invalidated, reusable time index.

Planning evaluates multiple shelf sides and legs against the same reservations.
Index once per revision, instead of scanning the entire table for every leg.
"""

from collections import defaultdict


class VertexReservations(set):
    def __init__(self, values=()):
        super().__init__(values)
        self._timeline = None

    def timeline(self):
        if self._timeline is None:
            index = defaultdict(list)
            for t, p in self:
                index[p].append(t)
            self._timeline = {p: sorted(times) for p, times in index.items()}
        return self._timeline

    def add(self, value):
        super().add(value)
        self._timeline = None

    def discard(self, value):
        super().discard(value)
        self._timeline = None

    def remove(self, value):
        super().remove(value)
        self._timeline = None

    def clear(self):
        super().clear()
        self._timeline = None

    def pop(self):
        value = super().pop()
        self._timeline = None
        return value

    def update(self, *values):
        super().update(*values)
        self._timeline = None

    def difference_update(self, *values):
        super().difference_update(*values)
        self._timeline = None

    def intersection_update(self, *values):
        super().intersection_update(*values)
        self._timeline = None

    def symmetric_difference_update(self, value):
        super().symmetric_difference_update(value)
        self._timeline = None

    def __ior__(self, value):
        self.update(value)
        return self

    def __iand__(self, value):
        self.intersection_update(value)
        return self

    def __isub__(self, value):
        self.difference_update(value)
        return self

    def __ixor__(self, value):
        self.symmetric_difference_update(value)
        return self


def reservations(plans, start):
    vertices, edges = VertexReservations(), set()
    for path in plans:
        vertices.update((start + i, p) for i, p in enumerate(path))
        edges.update((start + i, a, b) for i, (a, b) in enumerate(zip(path, path[1:])))
    return vertices, edges


class PlanReservations:
    """Spatially filtered absolute-time reservations with O(1) hold shifts.

    A pure delay changes an origin and a small stationary override, preserving
    the immutable base route. Only real route replacement rebuilds cell users.
    """

    def __init__(self, plans, start):
        self.routes = {}
        self.users = defaultdict(set)
        for vehicle, path in enumerate(plans):
            self.replace(vehicle, path, start)

    def replace(self, vehicle, path, start):
        old = self.routes.get(vehicle)
        if old is not None:
            for point in old["times"]:
                self.users[point].discard(vehicle)
                if not self.users[point]:
                    del self.users[point]
        times = defaultdict(list)
        for i, point in enumerate(path):
            times[point].append(i)
        self.routes[vehicle] = dict(path=tuple(path), origin=start, hold=None, times=dict(times))
        for point in times:
            self.users[point].add(vehicle)

    def at(self, vehicle, time):
        route = self.routes[vehicle]
        hold = route["hold"]
        if hold is not None and hold[0] <= time < hold[1]:
            return hold[2]
        index = min(max(0, time - route["origin"]), len(route["path"]) - 1)
        return route["path"][index]

    def hold(self, vehicle, start, steps):
        point = self.at(vehicle, start)
        route = self.routes[vehicle]
        route["origin"] += steps
        route["hold"] = (start, start + steps, point)

    def conflict(self, path, start, vehicle):
        for i, point in enumerate(path):
            time = start + i
            if any(
                peer != vehicle and self.at(peer, time) == point
                for peer in self.users.get(point, ())
            ):
                return "vertex"
            if i and any(
                peer != vehicle
                and self.at(peer, time - 1) == point
                and self.at(peer, time) == path[i - 1]
                for peer in self.users.get(point, ())
            ):
                return "edge"
        end, tail = start + len(path) - 1, path[-1]
        for peer in self.users.get(tail, ()):
            if peer == vehicle:
                continue
            route = self.routes[peer]
            if route["path"][-1] == tail:
                return "vertex"
            hold = route["hold"]
            if hold is not None and hold[2] == tail and max(end, hold[0]) < hold[1]:
                return "vertex"
            for index in reversed(route["times"][tail]):
                time = route["origin"] + index
                if time < end:
                    break
                if hold is None or not hold[0] <= time < hold[1]:
                    return "vertex"
        return None
