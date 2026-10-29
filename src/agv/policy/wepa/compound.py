"""Bounded owner exchanges coupled to order changes, with no future data.

Derived from the successful four-job pilot; no exact solution is an input.
Round-robin seeds avoid spending the whole budget on the first exchange in
larger queues. When no cross-owner pair exists, use targeted owner transfers.
The reservation-free proxy only ranks; physical SIPP previews accept plans.
"""

from agv.policy.wepa.targeted import neighborhoods


def compound_neighbors(costs, order, owners, *, limit=48):
    if len(order) < 2 or limit <= 0:
        return []
    local = neighborhoods(costs, order, owners, limit=100000)
    exchanges = [item for item in local if item[2] == "target_exchange"]
    seeds = []
    for o, a, kind in exchanges:
        changed = [j for j in o if a[j] != owners[j]]
        if len(changed) != 2:
            continue
        i, j = map(o.index, changed)
        first = list(o)
        first[i], first[j] = first[j], first[i]
        variants = [first]
        for pos in range(len(first) - 1):
            v = list(first)
            v[pos], v[pos + 1] = v[pos + 1], v[pos]
            variants.append(v)
        seeds.append((variants, a, "compound_exchange_reorder"))
    if not seeds:
        for o, a, kind in local:
            if kind != "target_transfer":
                continue
            job = next(j for j in o if a[j] != owners[j])
            variants = []
            for pos in sorted(
                {0, max(0, o.index(job) - 1), min(len(o) - 1, o.index(job) + 1), len(o) - 1}
            ):
                v = list(o)
                v.insert(pos, v.pop(v.index(job)))
                variants.append(v)
            seeds.append((variants, a, "compound_transfer_reorder"))
    result = []
    seen = {(tuple(order), tuple(owners[j] for j in order))}
    for round_index in range(max((len(v) for v, _, _ in seeds), default=0)):
        for variants, a, kind in seeds:
            if round_index >= len(variants):
                continue
            o = variants[round_index]
            key = tuple(o), tuple(a[j] for j in o)
            if key in seen:
                continue
            seen.add(key)
            result.append((list(o), dict(a), kind))
            if len(result) >= limit:
                return result
    return result
