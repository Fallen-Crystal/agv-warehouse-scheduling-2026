"""Exact visible-batch assignment + periodic feasible joint suffix repair."""

from agv.dispatch.greedy import greedy_action
from agv.domain import Task
from agv.planning.geometry import from_observation
from agv.planning.joint import JointPlanner
from agv.simulation import Environment


def matching_action(observation, age_weight=0.25):
    """Max-cardinality min-cost batch matching, DP over <=10 vehicle bits.

    Objective: static pickup+delivery+service - weight*visible order age.
    Exact for this matrix only, not for future routes or global schedules.
    """
    vehicles = [v for v in observation["vehicles"] if v["available"]]
    dispatchable = [j for j in observation["pending"] if j.get("dispatchable", True)]
    if not vehicles or not dispatchable:
        return []
    s, router = from_observation(observation)
    now = observation["time"]
    dp = {0: (0.0, [])}
    vehicle_positions = [(v["id"], tuple(v["position"])) for v in vehicles]
    for data in dispatchable:
        j = Task.from_mapping(data)
        points = s.pickup_candidates(j)
        base = j.pickup_service + j.delivery_service - age_weight * (now - j.release)
        costs = [
            min(router.distance(pos, p, vid) + router.distance(p, j.delivery, vid) for p in points)
            + base
            for vid, pos in vehicle_positions
        ]
        updated = dict(dp)
        for mask, (cost, pairs) in dp.items():
            for i, (vid, _) in enumerate(vehicle_positions):
                if mask & (1 << i) or costs[i] == float("inf"):
                    continue
                newmask = mask | (1 << i)
                item = (cost + costs[i], pairs + [(vid, j.id)])
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
    initial_rollout=False,
):
    if assignment not in ("matching", "greedy") or type(interval) is not int or interval < 1:
        raise ValueError("Invalid optimizer options")
    if type(joint) is not bool or type(initial_rollout) is not bool:
        raise ValueError("joint and initial_rollout must be booleans")
    initial = []
    if initial_rollout and joint:
        from agv.dispatch.initial_batch import choose_initial

        initial = choose_initial(
            scenario,
            attempts=attempts,
            interval=interval,
            router_kind=router_kind,
            neighborhoods=neighborhoods,
            trial_budget=trial_budget,
            ranker=ranker,
        )
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
        pairs = initial if (env.time == 0 and initial) else action(env.observe())
        feedback = env.assign(pairs)
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
    if initial_rollout:
        result["algorithm"]["initial_rollout"] = bool(initial)
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
