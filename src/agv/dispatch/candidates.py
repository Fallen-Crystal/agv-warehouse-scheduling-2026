"""Deterministic, legal ordered dispatch batches from visible state only."""

from collections import Counter
from dataclasses import dataclass
from math import isfinite

from agv.dispatch.greedy import greedy_action
from agv.dispatch.optimized import matching_action
from agv.domain import Scenario, Task
from agv.planning.astar import Router


@dataclass(frozen=True)
class Batch:
    id: str
    pairs: tuple
    reason: str


def legalize(pairs, observation):
    """Keep valid first occurrences; do not reinterpret or mutate the action.

    This is a policy-side filter. The real executor still validates the full
    batch and plans each reservation sequentially before accepting any job.
    """
    vehicles = {v["id"] for v in observation["vehicles"] if v["available"]}
    jobs = {
        j["id"]: j
        for j in observation["pending"]
        if j["release"] <= observation["time"] and j.get("dispatchable", True)
    }
    strict = observation["map"].get("map_info", {}).get("model_version") in (
        "math-v4-integrated",
        "mixed-v9",
    )
    chosen, used_vehicles, used_jobs, resources = [], set(), set(), set()
    if not isinstance(pairs, (list, tuple)):
        return chosen
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        v, j = pair
        if type(v) is not int or type(j) is not int or v not in vehicles or j not in jobs:
            continue
        resource = tuple(jobs[j]["shelf"]) if jobs[j].get("shelf") is not None else None
        if v in used_vehicles or j in used_jobs or (strict and resource in resources):
            continue
        chosen.append((v, j))
        used_vehicles.add(v)
        used_jobs.add(j)
        resources.add(resource)
    return chosen


def _costs(observation):
    geometry = Scenario.from_observation_map(observation["map"], observation["horizon"])
    router = Router(geometry)
    vehicles = [v for v in observation["vehicles"] if v["available"]]
    jobs, costs = {}, {}
    for data in observation["pending"]:
        if not data.get("dispatchable", True) or data["release"] > observation["time"]:
            continue
        job = Task(
            **{
                **{
                    k: v
                    for k, v in data.items()
                    if k not in ("dispatchable", "dispatch_block_reason")
                },
                "pickup": tuple(data["pickup"]) if data["pickup"] is not None else None,
                "shelf": tuple(data["shelf"]) if data["shelf"] is not None else None,
                "delivery": tuple(data["delivery"]),
            }
        )
        jobs[job.id] = data
        for v in vehicles:
            costs[v["id"], job.id] = (
                min(
                    router.distance(tuple(v["position"]), p, v["id"])
                    + router.distance(p, job.delivery, v["id"])
                    for p in geometry.pickup_candidates(job)
                )
                + job.pickup_service
                + job.delivery_service
            )
    return vehicles, jobs, costs


def make_batches(observation, max_batches=6, include=None, mode="full"):
    """Up to six distinct pairings/orders; no factorial action enumeration.

    ``mode='order'`` keeps the fallback pair set fixed to isolate reservation
    order. ``full`` also tries matching and visible order priority rules.
    """
    if type(max_batches) is not int or not 0 <= max_batches <= 32:
        raise ValueError("max_batches must be 0..32")
    if mode not in ("full", "order"):
        raise ValueError("Unknown candidate mode")
    if not max_batches:
        return []
    safe = legalize(greedy_action(observation) if include is None else include, observation)
    batches, seen = [], set()

    def add(name, pairs, reason):
        action = tuple(legalize(pairs, observation))
        if action not in seen and len(batches) < max_batches:
            seen.add(action)
            batches.append(Batch(name, action, reason))

    add("greedy", safe, "distance greedy fallback")
    if len(safe) < 2:
        return batches
    if mode == "order":
        add("reverse", safe[::-1], "same pairs, reverse reservation priority")
        for i in range(len(safe) - 1):
            swapped = safe[:]
            swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
            add(f"swap_{i}", swapped, "same pairs, adjacent reservation priority exchange")
        return batches
    add("matching", matching_action(observation), "visible max-cardinality static-cost matching")
    vehicles, jobs, costs = _costs(observation)
    minimum = {j: min(costs[v["id"], j] for v in vehicles) for j in jobs}

    def ordered(ids):
        available, action = {v["id"] for v in vehicles}, []
        for j in ids:
            if not available:
                break
            v = min(available, key=lambda k: (costs[k, j], k))
            if isfinite(costs[v, j]):
                action.append((v, j))
                available.remove(v)
        return action

    oldest = sorted(jobs, key=lambda j: (jobs[j]["release"], j))
    longest = sorted(jobs, key=lambda j: (-minimum[j], jobs[j]["release"], j))
    delivery_load = Counter(tuple(j["delivery"]) for j in observation["pending"])
    face_load = Counter(tuple(j["shelf"] or j["pickup"]) for j in observation["pending"])
    constrained = sorted(
        jobs,
        key=lambda j: (
            -delivery_load[tuple(jobs[j]["delivery"])],
            -face_load[tuple(jobs[j]["shelf"] or jobs[j]["pickup"])],
            -minimum[j],
            jobs[j]["release"],
            j,
        ),
    )
    add("oldest", ordered(oldest), "oldest released legal orders first")
    add("longest", ordered(longest), "longest static completion estimate first")
    add("constrained", ordered(constrained), "shared delivery / queued shelf resource first")
    add("reverse", safe[::-1], "same greedy pairs, reverse reservation priority")
    return batches
