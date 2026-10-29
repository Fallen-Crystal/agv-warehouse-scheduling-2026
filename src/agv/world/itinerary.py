"""Immutable route storage with O(1) cursor advancement and snapshot sharing."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, init=False, eq=False)
class Itinerary(Sequence):
    cells: tuple
    cursor: int

    def __init__(self, cells, cursor=0):
        if isinstance(cells, Itinerary):
            object.__setattr__(self, "cells", cells.cells)
            object.__setattr__(self, "cursor", cells.cursor + cursor)
        else:
            object.__setattr__(self, "cells", tuple(tuple(cell) for cell in cells))
            object.__setattr__(self, "cursor", cursor)
        if not 0 <= self.cursor < len(self.cells):
            raise ValueError("An itinerary must retain a current position")

    def __len__(self):
        return len(self.cells) - self.cursor

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self.cells[self.cursor + index]

    def __eq__(self, other):
        return isinstance(other, Sequence) and list(self) == list(other)

    def __add__(self, other):
        return list(self) + list(other)

    def __radd__(self, other):
        return list(other) + list(self)

    def __deepcopy__(self, memo):
        return list(self)

    def advance(self):
        return Itinerary(self, min(1, len(self) - 1))
