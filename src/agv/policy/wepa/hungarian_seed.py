"""Two deterministic virtual matching schedules for GA initialization only."""

from agv.policy.wepa.hungarian import linear_batch, minimum_assignment


def seeds(costs, order, owners, objective):
    w = costs.world
    result = []
    details = []
    seen = {(tuple(order), tuple(owners[j] for j in order))}
    for mode in ("duration", "linear"):
        times = [r["end"] if r else w.time for r in w.active]
        positions = [r["drop"] if r else w.plans[k][0] for k, r in enumerate(w.active)]
        locks = dict(w.locks)
        pending = list(order)
        o = []
        a = {}
        solves = 0
        rounds = 0
        fixed = max([w.time] + [r["end"] for r in w.records])
        clock = w.time
        while pending:
            cars = [k for k, t in enumerate(times) if t <= clock]
            ready = [
                j
                for j in pending
                if costs.predecessor.get(j) not in pending
                and locks.get(costs.slots[j]["bay"], 0) <= clock
            ]
            edges = {}
            for k in cars:
                for j in ready:
                    costs.details(k, positions[k], costs.jobs[j])
                    d, approach, pickup, drop, ps, ds = costs.cache[k, tuple(positions[k]), j]
                    edges[k, j] = (d + ps + ds, d)
            if mode == "duration":
                picked = minimum_assignment([[edges[k, j][0] for j in ready] for k in cars])
                pairs = [(cars[i], ready[h]) for i, h in picked]
                solves += bool(cars and ready)
            else:
                pairs, meta = linear_batch(
                    cars, ready, edges, objective, clock, fixed, len(w.visible)
                )
                solves += meta["solves"]
            if not pairs:
                events = [t for t in times if t > clock] + [t for t in locks.values() if t > clock]
                if not events:
                    break
                clock = min(events)
                continue
            rounds += 1
            for k, j in pairs:
                d, approach, pickup, drop, ps, ds = costs.cache[k, tuple(positions[k]), j]
                finish = clock + d + ps + ds
                times[k] = finish
                positions[k] = drop
                fixed = max(fixed, finish)
                locks[costs.slots[j]["bay"]] = (
                    finish if costs.jobs[j]["kind"] == "delivery" else clock + approach + ps
                )
                pending.remove(j)
                o.append(j)
                a[j] = k
        if not pending:
            key = tuple(o), tuple(a[j] for j in o)
            if key not in seen:
                seen.add(key)
                result.append((o, a, "hungarian_seed_" + mode))
        details.append(dict(mode=mode, complete=not pending, rounds=rounds, solves=solves))
    return result, dict(
        generated=len(result),
        variants=details,
        used_unpublished=False,
        routing_previews=0,
        exact_only_for_each_fixed_edge_batch=True,
    )
