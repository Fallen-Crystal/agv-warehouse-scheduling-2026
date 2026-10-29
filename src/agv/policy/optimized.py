"""Exact visible-batch assignment + periodic feasible joint suffix repair."""

from agv.core import Task
from agv.planning.astar import Router
from agv.warehouse.scenarios import Scenario


def matching_action(observation, age_weight=0.25):
    """Max-cardinality min-cost batch matching, DP over <=10 vehicle bits.

    Objective: static pickup+delivery+service - weight*visible order age.
    Exact for this matrix only, not for future routes or global schedules.
    """
    s = Scenario.from_observation_map(observation["map"], observation["horizon"])
    router = Router(s)
    vehicles = [v for v in observation["vehicles"] if v["available"]]
    dp = {0: (0.0, [])}
    for data in observation["pending"]:
        if not data.get("dispatchable", True):
            continue
        j = Task(
            **{
                **{
                    k: v
                    for k, v in data.items()
                    if k not in ("dispatchable", "dispatch_block_reason")
                },
                "pickup": tuple(data["pickup"]) if data["pickup"] else None,
                "shelf": tuple(data["shelf"]) if data["shelf"] else None,
                "delivery": tuple(data["delivery"]),
            }
        )
        costs = [
            min(
                router.distance(tuple(v["position"]), p, v["id"])
                + router.distance(p, j.delivery, v["id"])
                for p in s.pickup_candidates(j)
            )
            + j.pickup_service
            + j.delivery_service
            - age_weight * (observation["time"] - j.release)
            for v in vehicles
        ]
        updated = dict(dp)
        for mask, (cost, pairs) in dp.items():
            for i, v in enumerate(vehicles):
                if mask & (1 << i) or costs[i] == float("inf"):
                    continue
                newmask = mask | (1 << i)
                item = (cost + costs[i], pairs + [(v["id"], j.id)])
                if newmask not in updated or item < updated[newmask]:
                    updated[newmask] = item
        dp = updated
    mask = min(dp, key=lambda b: (-b.bit_count(), dp[b]))
    return dp[mask][1]
