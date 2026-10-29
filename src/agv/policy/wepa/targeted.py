"""Small deterministic neighborhoods around late work and costly approaches.

This is a targeted destroy/reinsert neighborhood, not a claim to implement the
complete adaptive LNS algorithm or to inherit its experimental performance.
"""

from itertools import combinations


def neighborhoods(costs, order, owners, *, limit=48):
    if not order:
        return []
    records = costs.projected
    jobs = costs.jobs
    cars = len(costs.obs["vehicles"])
    finish = {
        k: max([costs.world.time] + [r["end"] for r in records.values() if r["vehicle"] == k])
        for k in range(cars)
    }
    late = max(finish, key=lambda k: (finish[k], -k))
    tail = sorted((j for j in order if owners[j] == late), key=lambda j: (-records[j]["end"], j))[
        :3
    ]
    approaches = {}
    positions = {
        k: (
            costs.world.active[k]["drop"]
            if costs.world.active[k]
            else costs.obs["vehicles"][k]["position"]
        )
        for k in range(cars)
    }
    for j in order:
        approaches[j] = costs.details(owners[j], positions[owners[j]], jobs[j])[1]
    expensive = sorted(order, key=lambda j: (-approaches[j], j))[:3]
    targets = list(dict.fromkeys(tail + expensive))
    proposals, seen = [], {(tuple(order), tuple(owners[j] for j in order))}

    def add(o, a, kind):
        key = tuple(o), tuple(a[j] for j in o)
        if key not in seen:
            seen.add(key)
            proposals.append((list(o), dict(a), kind))

    # Change ownership in isolation first: route feasibility is checked later by
    # complete SIPP previews, and predecessor constraints remain in the proxy.
    for j in targets:
        choices = sorted(
            (costs.details(k, positions[k], jobs[j])[0], finish[k], k)
            for k in range(cars)
            if k != owners[j]
        )
        for _, _, k in choices[:2]:
            a = dict(owners)
            a[j] = k
            add(order, a, "target_transfer")
    # Reinsert relative to the target owner's first and last jobs, and move
    # expensive approaches earlier without disrupting every chromosome gene.
    for j in targets:
        index = order.index(j)
        for pos in sorted({0, max(0, index - 2), min(len(order) - 1, index + 2), len(order) - 1}):
            o = list(order)
            o.insert(pos, o.pop(index))
            add(o, owners, "target_reinsert")
    for j in targets[:4]:
        peers = sorted(
            (q for q in order if owners[q] != owners[j]),
            key=lambda q: (abs(records[q]["end"] - records[j]["end"]), q),
        )[:2]
        for q in peers:
            a = dict(owners)
            a[j], a[q] = a[q], a[j]
            add(order, a, "target_exchange")
    for j, q in combinations(targets[:4], 2):
        o = list(order)
        i, h = o.index(j), o.index(q)
        o[i], o[h] = o[h], o[i]
        add(o, owners, "target_order_swap")
    return proposals[:limit]
