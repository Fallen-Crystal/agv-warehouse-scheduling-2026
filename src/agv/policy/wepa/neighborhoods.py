"""Deterministic joint ownership and sequence candidate neighborhoods."""

import random


def neighbors(order, owners, vehicles, *, seed=0, limit=192):
    """Unique relocate, ownership-swap and sequence neighborhoods of one plan."""
    rng, seen, result = random.Random(seed), set(), []

    def add(sequence, assignment, kind):
        key = tuple(sequence), tuple(assignment[j] for j in sequence)
        if key not in seen and len(result) < limit:
            seen.add(key)
            result.append((list(sequence), dict(assignment), kind))

    for j in rng.sample(list(order), len(order)):
        for k in rng.sample(list(range(vehicles)), vehicles):
            if k != owners[j]:
                assignment = dict(owners)
                assignment[j] = k
                add(order, assignment, "relocate")
    for _ in range(limit * 4):
        if len(order) < 2 or len(result) >= limit:
            break
        a, b = rng.sample(range(len(order)), 2)
        sequence, assignment = list(order), dict(owners)
        if rng.random() < 0.5:
            assignment[order[a]], assignment[order[b]] = assignment[order[b]], assignment[order[a]]
            kind = "swap_owners"
        else:
            sequence.insert(b, sequence.pop(a))
            kind = "relocate_order"
        add(sequence, assignment, kind)
    return result
