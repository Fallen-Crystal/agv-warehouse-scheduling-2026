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
    table = ReservationTable(plans, start)
    vertices, edges = table.view_excluding(None, start)
    return VertexReservations(vertices), set(edges)


class ReservationTable:
    """Spatially filtered absolute-time reservations with O(1) hold shifts.

    A pure delay changes an origin and a small stationary override, preserving
    the immutable base route. Only real route replacement rebuilds cell users.
    """

    def __init__(self, plans, start):
        self.version = 0
        self.routes = {}
        self.users = defaultdict(set)
        for vehicle, path in enumerate(plans):
            self.replace(vehicle, path, start)

    def replace(self, vehicle, path, start):
        self.version += 1
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
        self.version += 1
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

    def view_excluding(self, vehicle, start):
        return ReservationView(self, vehicle, start, False), ReservationView(
            self, vehicle, start, True
        )


class ReservationView:
    """Read-only, live absolute-time view; no per-assignment route reinsertion."""

    def __init__(self, table, excluded, start, edges):
        self.table, self.excluded, self.start, self.edges = table, excluded, start, edges
        self._timeline = None
        self._version = table.version

    def __contains__(self, value):
        time, point = value[:2]
        if time < self.start:
            return False
        for peer in self.table.users.get(point, ()):
            if peer == self.excluded:
                continue
            route = self.table.routes[peer]
            end = max(self.start, route["origin"] + len(route["path"]) - 1)
            if time > end or (self.edges and time >= end):
                continue
            if self.table.at(peer, time) == point and (
                not self.edges or self.table.at(peer, time + 1) == value[2]
            ):
                return True
        return False

    def __iter__(self):
        for peer, route in self.table.routes.items():
            if peer == self.excluded:
                continue
            end = max(self.start, route["origin"] + len(route["path"]) - 1)
            for time in range(self.start, end + (0 if self.edges else 1)):
                point = self.table.at(peer, time)
                yield (time, point, self.table.at(peer, time + 1)) if self.edges else (time, point)

    def timeline(self):
        if self._version != self.table.version:
            self._timeline = None
            self._version = self.table.version
        if self._timeline is None:
            index = defaultdict(set)
            for time, point in self:
                index[point].add(time)
            self._timeline = {p: sorted(times) for p, times in index.items()}
        return self._timeline


PlanReservations = ReservationTable
