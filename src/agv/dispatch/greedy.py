"""接入示例：只读取可见状态的静态距离贪心；不是创新算法。"""

from agv.domain import Scenario, Task
from agv.planning.astar import Router
from agv.simulation import Environment


def greedy_action(observation):
    geometry = Scenario.from_observation_map(observation["map"], observation["horizon"])
    router = Router(geometry)
    candidates = []
    for v in observation["vehicles"]:
        if v["available"]:
            for j in observation["pending"]:
                if not j.get("dispatchable", True):
                    continue
                job = Task(
                    j["id"],
                    tuple(j["pickup"]) if j["pickup"] is not None else None,
                    tuple(j["delivery"]),
                    shelf=tuple(j["shelf"]) if j.get("shelf") is not None else None,
                )
                points = geometry.pickup_candidates(job)
                distance = min(
                    router.distance(v["position"], p, v["id"])
                    + router.distance(p, job.delivery, v["id"])
                    for p in points
                )
                candidates.append(
                    (
                        distance + j["pickup_service"] + j["delivery_service"],
                        j["release"],
                        j["id"],
                        v["id"],
                    )
                )
    used_vehicles, used_jobs, pairs = set(), set(), []
    for cost, release, j, k in sorted(candidates):
        if cost != float("inf") and k not in used_vehicles and j not in used_jobs:
            pairs.append((k, j))
            used_vehicles.add(k)
            used_jobs.add(j)
    if geometry.is_v9_1:
        from agv.dispatch.candidates import legalize

        return legalize(pairs, observation)
    return pairs


def run(scenario, policy=greedy_action):
    env = Environment(scenario)
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        try:
            action = policy(env.observe())
        except Exception as error:
            env._execution_error = dict(
                kind="policy_error", type=type(error).__name__, message=str(error), time=env.time
            )
            break
        try:
            feedback = env.assign(action)
        except ValueError as error:
            env._execution_error = dict(
                kind="invalid_action", type="ValueError", message=str(error), time=env.time
            )
            break
        if env.stop_if_stalled(feedback):
            break
        env.advance(observe=False)
    return env.result()
