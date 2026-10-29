"""Historical exact bitmask assignment with unchanged deterministic tie rules."""

import math


def match_batch(vehicles, jobs, cost):
    """Exact max-cardinality min-cost assignment for this fixed visible batch."""
    states = {0: (0, ())}
    for job in jobs:
        updated = dict(states)
        for mask, (value, pairs) in states.items():
            for i, vehicle in enumerate(vehicles):
                if mask >> i & 1:
                    continue
                edge = cost(vehicle, job)
                if not math.isfinite(edge):
                    continue
                new = mask | 1 << i
                item = value + edge, pairs + ((vehicle["id"], job["id"]),)
                if new not in updated or item < updated[new]:
                    updated[new] = item
        states = updated
    best = min(states, key=lambda m: (-m.bit_count(), states[m]))
    return list(states[best][1])
