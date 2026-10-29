"""Original instantaneous minimum-cost batch assignment, with real SIPP commit."""

from math import isfinite

from agv.policy.wepa.exact_matching import match_batch


def matching(world):
    cars = [dict(id=k, position=p[0]) for k, p in enumerate(world.plans) if world.active[k] is None]
    jobs = world.ready()
    pairs = match_batch(cars, jobs, lambda v, j: world.estimate(v["id"], j))
    accepted = []
    for k, jid in pairs:
        job = next((j for j in world.ready() if j["id"] == jid), None)
        if job is None:
            continue
        proposal = world.trip(k, job)
        if proposal is not None:
            world.commit(k, job, proposal)
            accepted.append((k, jid))
    return accepted


def linear_assignment(cars, jobs, edges, objective, now, fixed_finish, visible_count):
    """Exact batch assignment for fixed estimated edges and current linear cost.

    Each edge contains (duration, distance). Enumerate the bottleneck threshold,
    then solve the additive residual with the original exact bitmask matcher.
    This is not a full-horizon or conflict-coupled global optimality claim.
    """
    if not jobs:
        return []
    if len(jobs) > len(cars):
        raise ValueError("Low-load matching requires jobs <= free vehicles")
    wt, wr, wd = (w / s for w, s in zip(objective.weights, objective.scales))
    wr /= max(1, visible_count)
    thresholds = sorted(
        {
            now + duration
            for duration, distance in edges.values()
            if isfinite(duration) and isfinite(distance)
        }
    )
    best = None
    for threshold in thresholds:

        def cost(vehicle, job):
            duration, distance = edges[vehicle["id"], job["id"]]
            if now + duration > threshold:
                return float("inf")
            return wr * (now + duration - job.get("release", 0)) + wd * distance

        pairs = match_batch(cars, jobs, cost)
        if len(pairs) != len(jobs):
            continue
        finish = max([fixed_finish] + [now + edges[k, j][0] for k, j in pairs])
        residual = sum(
            cost(next(v for v in cars if v["id"] == k), next(j for j in jobs if j["id"] == jid))
            for k, jid in pairs
        )
        item = wt * finish + residual, tuple(pairs)
        if best is None or item < best:
            best = item
    return list(best[1]) if best else []


def matching_linear(world, objective):
    cars = [dict(id=k, position=p[0]) for k, p in enumerate(world.plans) if world.active[k] is None]
    jobs = world.ready()
    edges = {}
    for v in cars:
        k = v["id"]
        for j in jobs:
            choices = []
            for a, b, ps, ds in world.endpoints(j):
                distance = world.router.distance(v["position"], a, k) + world.router.distance(
                    a, b, k
                )
                choices.append((distance + ps + ds, distance))
            edges[k, j["id"]] = min(choices)
    pairs = linear_assignment(
        cars,
        jobs,
        edges,
        objective,
        world.time,
        max((r["end"] for r in world.records), default=0),
        len(world.visible),
    )
    accepted = []
    for k, jid in pairs:
        job = next((j for j in world.ready() if j["id"] == jid), None)
        if job is None:
            continue
        proposal = world.trip(k, job)
        if proposal is not None:
            world.commit(k, job, proposal)
            accepted.append((k, jid))
    return accepted
