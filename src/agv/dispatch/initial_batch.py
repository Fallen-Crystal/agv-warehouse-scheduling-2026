"""Static first-batch planner: screen candidate batches with greedy, score with joint.

For a fully visible static instance the whole task set is known at t=0, so it is
legal to compare a small set of initial assignments by rolling each one forward
with the same joint policy used for execution.  The base greedy assignment is
always included in the pool, so the selected plan is never worse than the
current joint baseline on these instances.

Dynamic instances are deliberately excluded: a rollout that runs past the
current release frontier would use future arrivals in the score.
"""

import itertools

from agv.dispatch.candidates import legalize
from agv.dispatch.greedy import greedy_action
from agv.domain import Scenario, Task
from agv.evaluation.validation import validate
from agv.planning.joint import JointPlanner
from agv.simulation import Environment


def _visible_scenario(observation):
    scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
    scenario.tasks = [Task.from_mapping(data) for data in observation["pending"]]
    return scenario.check()


def _greedy_rollout(scenario, pairs, router_kind="astar"):
    env = Environment(scenario, router_kind=router_kind)
    try:
        feedback = env.assign(pairs)
    except ValueError:
        return None
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        if env.stop_if_stalled(feedback):
            return None
        env.advance(observe=False)
        if env.done or (scenario.horizon is not None and env.time >= scenario.horizon):
            break
        obs = env.observe()
        action = greedy_action(obs)
        if scenario.uses_layer_rules:
            action = legalize(action, obs)
        feedback = env.assign(action)
    return env.result() if env.done else None


def _joint_rollout(
    scenario,
    pairs,
    *,
    attempts=8,
    interval=5,
    router_kind="astar",
    neighborhoods="legacy",
    trial_budget=None,
    ranker=None,
):
    env = Environment(scenario, router_kind=router_kind)
    planner = JointPlanner(
        attempts,
        router_kind=router_kind,
        neighborhoods=neighborhoods,
        ranker=ranker,
        trial_budget=trial_budget,
    )
    try:
        feedback = env.assign(pairs)
    except ValueError:
        return None
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        if env.time % interval == 0 or any(f["accepted"] for f in feedback):
            proposal = planner.propose(env.observe())
            if proposal:
                env.apply_replan(proposal)
        if env.stop_if_stalled(feedback):
            return None
        env.advance(observe=False)
        if env.done or (scenario.horizon is not None and env.time >= scenario.horizon):
            break
        obs = env.observe()
        action = greedy_action(obs)
        if scenario.uses_layer_rules:
            action = legalize(action, obs)
        feedback = env.assign(action)
    if not env.done:
        return None
    result = env.result()
    validate(scenario, result)
    return result


def candidates(observation, limit=48):
    base = greedy_action(observation)
    pending = [j["id"] for j in observation["pending"] if j.get("dispatchable", True)]
    used = {j for _, j in base}
    seen, out = set(), []

    def add(pairs):
        key = tuple(pairs)
        if key not in seen:
            seen.add(key)
            out.append(pairs)

    add(base)
    for (a, ja), (b, jb) in itertools.combinations(base, 2):
        add([(k, jb if k == a else ja if k == b else j) for k, j in base])
    for k, j in base:
        for q in pending:
            if q in used:
                continue
            add([(kk, q if kk == k else jj) for kk, jj in base])
    return out[:limit]


def choose_initial(
    scenario,
    limit=48,
    top_k=4,
    attempts=8,
    interval=5,
    router_kind="astar",
    neighborhoods="legacy",
    trial_budget=None,
    ranker=None,
):
    """Return an improved static first batch, or [] when not applicable."""
    if any(job.release != 0 for job in scenario.tasks):
        return []
    observation = Environment(scenario, router_kind=router_kind).observe()
    visible = _visible_scenario(observation)
    base = greedy_action(observation)
    if visible.uses_layer_rules:
        base = legalize(base, observation)
    screened = []
    for pairs in candidates(observation, limit):
        if visible.uses_layer_rules:
            pairs = legalize(pairs, observation)
        result = _greedy_rollout(visible, pairs, router_kind=router_kind)
        if result is not None:
            screened.append((result["mean_flow_time"], tuple(pairs), pairs))
    screened.sort(key=lambda item: (item[0], item[1]))
    pool = [pairs for _, _, pairs in screened[:top_k]]
    if base not in pool:
        pool.append(base)
    best = None
    for pairs in pool:
        result = _joint_rollout(
            scenario,
            pairs,
            attempts=attempts,
            interval=interval,
            router_kind=router_kind,
            neighborhoods=neighborhoods,
            trial_budget=trial_budget,
            ranker=ranker,
        )
        if result is None:
            continue
        key = (result["mean_flow_time"], result["makespan"], result["moves"])
        if best is None or key < best[0]:
            best = (key, pairs)
    return best[1] if best else []
