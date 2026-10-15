"""Exact visible-batch assignment + periodic feasible joint suffix repair."""

from agv.dispatch.greedy import greedy_action
from agv.domain import Scenario, Task
from agv.planning.astar import Router
from agv.planning.joint import JointPlanner
from agv.simulation import Environment


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


def run(
    scenario,
    assignment="matching",
    joint=True,
    interval=5,
    attempts=8,
    router_kind="astar",
    neighborhoods="legacy",
    ranker=None,
    trial_budget=None,
    collect=None,
):
    if assignment not in ("matching", "greedy") or type(interval) is not int or interval < 1:
        raise ValueError("Invalid optimizer options")
    if type(joint) is not bool:
        raise ValueError("joint must be a boolean")
    env = Environment(scenario, router_kind=router_kind)
    planner = JointPlanner(
        attempts,
        router_kind=router_kind,
        neighborhoods=neighborhoods,
        ranker=ranker,
        trial_budget=trial_budget,
        collect=collect,
    )
    action = matching_action if assignment == "matching" else greedy_action
    calls = 0
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        feedback = env.assign(action(env.observe()))
        if joint and (env.time % interval == 0 or any(f["accepted"] for f in feedback)):
            calls += 1
            proposal = planner.propose(env.observe())
            if proposal:
                env.apply_replan(proposal)
        if env.stop_if_stalled(feedback):
            break
        env.advance(observe=False)
    result = env.result()
    result["joint_routing_stats"] = (
        dict(planner.router.stats) if planner.router else dict(calls=0, expanded=0, generated=0)
    )
    result["algorithm"] = dict(
        assignment=assignment,
        joint=joint,
        interval=interval,
        attempts=attempts,
        router=router_kind,
        neighborhoods=neighborhoods,
        trial_budget=trial_budget,
        learned_ranker=ranker is not None,
        replan_calls=calls,
        accepted_replans=len(result["replanning_events"]),
    )
    return result


if __name__ == "__main__":
    import json

    from agv.domain import example
    from agv.evaluation.validation import validate

    s = example(mode="dynamic", arrival="burst", size="medium", vehicles=6, task_count=30)
    r = run(s)
    validate(s, r)
    print(
        json.dumps(
            {k: r[k] for k in ("feasible", "makespan", "mean_flow_time", "moves", "algorithm")},
            indent=2,
        )
    )
