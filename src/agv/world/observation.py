"""Read-only online values and the historical detached-dict adapter.

Static geometry is frozen once per reset; dynamic fields are frozen once per
observation. deepcopy deliberately produces editable detached JSON containers.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass


def _readonly(*args, **kwargs):
    raise TypeError("Observation values are read-only")


class FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return {deepcopy(k, memo): deepcopy(v, memo) for k, v in self.items()}


class FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = (
        __iadd__
    ) = __imul__ = _readonly

    def __deepcopy__(self, memo):
        return [deepcopy(v, memo) for v in self]


def freeze(value):
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, dict):
        return FrozenDict({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return FrozenList(freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class Observation(Mapping):
    _values: Mapping

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __deepcopy__(self, memo):
        return deepcopy(self._values, memo)
