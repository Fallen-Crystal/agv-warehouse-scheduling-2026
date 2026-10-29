"""Rectangular Hungarian matching and instantaneous fixed-edge F surrogate.

No future requests, stock modifications, or route commitments during scoring.
Hungarian optimizes additive residuals. Threshold enumeration handles the
nonadditive makespan term for this fixed-edge batch only, not a full horizon.
"""

from math import inf, isfinite


def minimum_assignment(matrix):
    """Maximum-cardinality then minimum-cost matching, forbidden edges=inf.

    Hungarian primal-dual augmenting paths, with one dummy column per row.
    A cardinality penalty dominates every finite real-cost difference.
    """
    n = len(matrix)
    if not n:
        return []
    m = len(matrix[0])
    if any(len(row) != m for row in matrix):
        raise ValueError("Ragged matrix")
    finite = [v for row in matrix for v in row if isfinite(v)]
    if not finite or not m:
        return []
    low, high = min(finite), max(finite)
    span = high - low
    penalty = (n + 1) * (span + 1)
    forbidden = (n + 1) * penalty + n * span + 1
    a = [[x - low if isfinite(x) else forbidden for x in row] + [penalty] * n for row in matrix]
    width = m + n
    u = [0] * (n + 1)
    v = [0] * (width + 1)
    p = [0] * (width + 1)
    way = [0] * (width + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minimum = [inf] * (width + 1)
        used = [False] * (width + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, width + 1):
                if used[j]:
                    continue
                cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minimum[j]:
                    minimum[j] = cur
                    way[j] = j0
                if minimum[j] < delta:
                    delta = minimum[j]
                    j1 = j
            for j in range(width + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return sorted(
        (p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] and isfinite(matrix[p[j] - 1][j - 1])
    )


def linear_batch(cars, jobs, edges, objective, now, fixed_finish, visible_count):
    """Exact maximum-cardinality matching for an instantaneous edge estimate.

    R contribution uses new execution duration: elapsed waiting of every
    visible order is already fixed and must not disadvantage older requests
    when jobs outnumber idle cars. Unassigned future workload is not solved.
    """
    if not cars or not jobs:
        return [], dict(solves=0)
    wt, wr, wd = [w / s for w, s in zip(objective.weights, objective.scales)]
    wr /= max(1, visible_count)
    residual = [
        [
            wr * edges[k, j][0] + wd * edges[k, j][1]
            if all(isfinite(x) for x in edges[k, j])
            else inf
            for j in jobs
        ]
        for k in cars
    ]
    cardinality = len(minimum_assignment(residual))
    solves = 1
    thresholds = sorted(
        {
            max(fixed_finish, now + duration)
            for duration, distance in edges.values()
            if isfinite(duration) and isfinite(distance)
        }
    )
    best = None
    for threshold in thresholds:
        matrix = [
            [
                residual[i][h] if now + edges[k, j][0] <= threshold else inf
                for h, j in enumerate(jobs)
            ]
            for i, k in enumerate(cars)
        ]
        chosen = minimum_assignment(matrix)
        solves += 1
        if len(chosen) != cardinality:
            continue
        pairs = tuple((cars[i], jobs[h]) for i, h in chosen)
        finish = max([fixed_finish] + [now + edges[k, j][0] for k, j in pairs])
        cost = wt * finish + sum(residual[i][h] for i, h in chosen)
        item = cost, pairs
        if best is None or item < best:
            best = item
    return list(best[1]) if best else [], dict(
        solves=solves, cardinality=cardinality, fixed_edge_surrogate=best[0] if best else None
    )


def matching_hungarian(world, objective):
    cars = [k for k, r in enumerate(world.active) if r is None]
    jobs = sorted(world.ready(), key=lambda j: j["id"])
    ids = [j["id"] for j in jobs]
    edges = {}
    for k in cars:
        for job in jobs:
            edges[k, job["id"]] = min(
                (
                    world.router.distance(world.plans[k][0], a, k)
                    + world.router.distance(a, b, k)
                    + ps
                    + ds,
                    world.router.distance(world.plans[k][0], a, k) + world.router.distance(a, b, k),
                )
                for a, b, ps, ds in world.endpoints(job)
            )
    fixed = max([world.time] + [r["end"] for r in world.records])
    pairs, info = linear_batch(cars, ids, edges, objective, world.time, fixed, len(world.visible))
    accepted = []
    for k, jid in pairs:
        job = next((j for j in world.ready() if j["id"] == jid), None)
        if job is None:
            continue
        proposal = world.trip(k, job)
        if proposal is not None:
            world.commit(k, job, proposal)
            accepted.append((k, jid))
    return accepted, dict(
        info,
        proposed_pairs=pairs,
        accepted_pairs=accepted,
        idle_cars=len(cars),
        ready_jobs=len(ids),
    )
