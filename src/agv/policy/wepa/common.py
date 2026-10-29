"""Visible-world dispatch helpers; physical changes go through World.commit."""


def batch(world, rule):
    assignments = []
    for _ in range(len(world.plans)):
        cars = [k for k, r in enumerate(world.active) if r is None]
        jobs = world.ready()
        if not cars or not jobs:
            break
        estimates = {(k, j["id"]): world.estimate(k, j) for k in cars for j in jobs}
        if rule == "eta":
            choices = sorted(
                (estimates[k, j["id"]], j["release"], j["id"], k, j) for k in cars for j in jobs
            )
        else:

            def priority(j):
                service = min(ps + ds for _, _, ps, ds in world.endpoints(j))
                if rule == "inbound":
                    return (j["kind"] != "delivery", j["release"], j["id"])
                if rule == "outbound":
                    return (j["kind"] != "retrieval", j["release"], j["id"])
                if rule == "short":
                    return (min(estimates[k, j["id"]] for k in cars), service, j["id"])
                if rule == "long":
                    return (-min(estimates[k, j["id"]] for k in cars), j["release"], j["id"])
                return (j["release"], j["id"])

            ordered = sorted(jobs, key=priority)
            choices = [
                (estimates[k, j["id"]], j["release"], j["id"], k, j)
                for j in ordered
                for k in sorted(cars, key=lambda k: estimates[k, j["id"]])
            ]
        committed = False
        for _, _, _, k, j in choices:
            proposal = world.trip(k, j)
            if proposal is None:
                world.routing_failures += 1
                continue
            world.commit(k, j, proposal)
            assignments.append((k, j["id"]))
            committed = True
            break
        if not committed:
            break
    return assignments


def owned_batch(world, order, owners):
    pairs = []
    for jid in order:
        if jid in world.assigned or world.active[owners[jid]] is not None:
            continue
        job = next((j for j in world.ready() if j["id"] == jid), None)
        if job is None:
            continue
        k = owners[jid]
        proposal = world.trip(k, job)
        if proposal is None:
            world.routing_failures += 1
            continue
        world.commit(k, job, proposal)
        pairs.append((k, jid))
    return pairs


def values(world):
    return (
        max((r["end"] for r in world.records), default=0),
        sum(r["end"] - world.tasks[r["task"]]["release"] for r in world.records)
        / max(1, len(world.tasks)),
        world.past_moves,
    )
