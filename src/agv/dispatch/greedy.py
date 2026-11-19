"""接入示例：只读取可见状态的静态距离贪心；不是创新算法。"""

from agv.domain import Task
from agv.planning.geometry import from_observation
from agv.simulation import Environment


def greedy_action(observation):
    available = [v for v in observation["vehicles"] if v["available"]]
    dispatchable = [j for j in observation["pending"] if j.get("dispatchable", True)]
    if not available or not dispatchable:
        return []
    geometry, router = from_observation(observation)
    candidates = []
    for j in dispatchable:
        job = Task.from_mapping(j)
        points = geometry.pickup_candidates(job)
        service = job.pickup_service + job.delivery_service
        for v in available:
            vid = v["id"]
            pos = tuple(v["position"])
            distance = min(
                router.distance(pos, p, vid) + router.distance(p, job.delivery, vid) for p in points
            )
            candidates.append((distance + service, job.release, job.id, vid))
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
