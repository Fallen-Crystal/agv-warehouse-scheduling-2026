"""Bounded, exact ETA memoization; reservation changes never reuse old values."""

from collections import OrderedDict


class EtaCache:
    def __init__(self, capacity=256):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("ETA cache capacity must be a positive integer")
        self.capacity = capacity
        self._entries = OrderedDict()
        self.stats = dict(requests=0, hits=0, misses=0, invalidations=0, evictions=0)

    def get_or_compute(self, query, reservation_signature, compute):
        """One exact departure time per query; failures are valid cached answers."""
        self.stats["requests"] += 1
        if query in self._entries:
            signature, value = self._entries.pop(query)
            if signature == reservation_signature:
                self._entries[query] = (signature, value)
                self.stats["hits"] += 1
                return value
            self.stats["invalidations"] += 1
        self.stats["misses"] += 1
        value = compute()
        self._entries[query] = (reservation_signature, value)
        if len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
            self.stats["evictions"] += 1
        return value

    def snapshot(self):
        return dict(self.stats, capacity=self.capacity, entries=len(self._entries), time_bucket=1)
