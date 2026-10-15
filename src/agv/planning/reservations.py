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
