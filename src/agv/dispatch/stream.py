"""V9.1 opt-in dispatch ablations; every decision consumes only observe()."""

from agv.dispatch.assignment import minimum_assignment
from agv.dispatch.bcrd import fallback
from agv.dispatch.candidates import legalize
from agv.dispatch.positioning import PositioningPolicy
from agv.dispatch.shadow import _task
from agv.domain import Scenario
from agv.planning import create_router
from agv.planning.pickup import plan_task
from agv.planning.reservations import reservations
from agv.simulation import Environment


class ArrivalMatching:
    def __init__(self, observation, *, delay=False, max_wait=16, threshold=3):
        self.scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
        self.router = create_router("sipp", self.scenario)
        self.delay, self.max_wait, self.threshold = delay, max_wait, threshold
        self.log = []

    def action(self, observation):
        now = observation["time"]
        jobs = [j for j in observation["pending"] if j.get("dispatchable", True)]
        vehicles = [v for v in observation["vehicles"] if v["available"]]
        if not jobs or not vehicles:
            return []
        paths = [
            v["return_path"] if v["available"] else v["committed_path"]
            for v in observation["vehicles"]
        ]
        paths = [[tuple(p) for p in path] for path in paths]
        estimates = {}

        def estimate(vehicle, raw):
            key = (vehicle["id"], raw["id"])
            if key not in estimates:
                start = now if vehicle["available"] else vehicle["route_record"]["delivery_end"]
                position = (
                    tuple(vehicle["position"])
                    if vehicle["available"]
                    else paths[vehicle["id"]][start - now]
                )
                vertices, edges = reservations(
                    [p for k, p in enumerate(paths) if k != vehicle["id"]], now
                )
                _, record, failed, _ = plan_task(
                    self.scenario,
                    self.router,
                    _task(raw),
                    vehicle["id"],
                    position,
                    start,
                    vertices,
                    edges,
                )
                estimates[key] = float("inf") if failed else record["delivery_end"]
            return estimates[key]

        values = [
            [estimate(v, j) - j["release"] - 0.25 * (now - j["release"]) for j in jobs]
            for v in vehicles
        ]
        # Private dummy columns ensure feasibility, with maximal real cardinality.
        finite = [x for row in values for x in row if x != float("inf")]
        unmatched = (max([abs(x) for x in finite], default=1) + 1) * (len(jobs) + len(vehicles) + 1)
        matrix = [row + [unmatched] * len(vehicles) for row in values]
        selected = minimum_assignment(matrix)
        pairs, held = [], []
        for i, column in enumerate(selected):
            if column is None or column >= len(jobs) or values[i][column] == float("inf"):
                continue
            vehicle, job = vehicles[i], jobs[column]
            completion = estimate(vehicle, job)
            soon = [
                v
                for v in observation["vehicles"]
                if not v["available"]
                and 0 < v["route_record"]["delivery_end"] - now <= self.max_wait
            ]
            better = (
                min((estimate(v, job) for v in soon), default=float("inf"))
                if self.delay and now - job["release"] < self.max_wait
                else float("inf")
            )
            if better + self.threshold < completion:
                held.append(
                    dict(task_id=job["id"], available_completion=completion, busy_completion=better)
                )
            else:
                pairs.append((vehicle["id"], job["id"]))
        action = legalize(pairs, observation)
        self.log.append(dict(time=now, pairs=[list(p) for p in action], delayed=held))
        return action


def run(scenario, policy="greedy", *, positioning=False, delay=False):
    if not scenario.is_v9_1:
        raise ValueError("Stream optimization requires the V9.1 profile")
    if policy not in ("greedy", "matching") or (delay and policy != "matching"):
        raise ValueError("Invalid stream policy")
    env = Environment(scenario, router_kind="sipp", positioning=positioning)
    initial = env.observe()
    matcher = ArrivalMatching(initial, delay=delay) if policy == "matching" else None
    locator = PositioningPolicy(initial) if positioning else None
    attempts = rejects = 0
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        obs = env.observe()
        if locator:
            locator.observe(obs)
        action = matcher.action(obs) if matcher else fallback(obs)
        feedback = env.assign(action)
        if locator:
            for vehicle, target in locator.action(env.observe()):
                attempts += 1
                try:
                    env.reposition(vehicle, target)
                except ValueError:
                    rejects += 1
        if env.stop_if_stalled(feedback):
            break
        env.advance(observe=False)
    result = env.result()
    result["algorithm"] = dict(
        assignment="eta_matching" if matcher else "greedy",
        router="sipp",
        joint=False,
        positioning=positioning,
        delay=delay,
        position_attempts=attempts,
        position_rejections=rejects,
    )
    result["dispatch_decisions"] = matcher.log if matcher else []
    if matcher:
        result["decision_routing_stats"] = dict(matcher.router.stats)
        result["algorithm"].update(
            delay_max_wait=matcher.max_wait, delay_threshold=matcher.threshold
        )
    if locator:
        result["algorithm"]["positioning_parameters"] = dict(
            strength=locator.strength,
            sigma=locator.sigma,
            interval=locator.interval,
            capacity=locator.capacity,
            hysteresis=locator.hysteresis,
            history_decay_steps=200,
        )
    return result
