"""Pure candidate features shared by planning and learned ranking."""


def features(vehicles, plans, order, now):
    # Cheap observable proxy; labels come from actual feasible route repairs.
    waits = []
    remaining = []
    cells = []
    frozen = 0
    for k in order:
        path = plans[k]
        v = vehicles[k]
        waits.append(sum(a == b for a, b in zip(path, path[1:])))
        remaining.append(len(path) - 1)
        cells.append(set(path))
        frozen += v["state"] in ("loading", "unloading")
    overlap = sum(len(a & b) for i, a in enumerate(cells) for b in cells[i + 1 :])
    return [
        len(order),
        sum(waits),
        max(waits, default=0),
        overlap,
        sum(remaining),
        waits[0] if waits else 0,
        remaining[0] if remaining else 0,
        frozen,
    ]
