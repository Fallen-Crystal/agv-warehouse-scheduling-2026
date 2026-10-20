"""V9.1 opt-in dispatch ablations; every decision consumes only observe()."""

from agv.planning import create_router
from agv.planning.pickup import plan_task
from agv.policy.assignment import minimum_assignment
from agv.policy.candidates import legalize
from agv.policy.forecast import _task
from agv.warehouse.scenarios import Scenario
from agv.world.reservations import reservations


class ArrivalMatching:
    def __init__(self, observation, *, delay=False, max_wait=16, threshold=3, eta_cache=None):
        self.scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
        self.router = create_router("sipp", self.scenario)
        self.delay, self.max_wait, self.threshold = delay, max_wait, threshold
        self.eta_cache = eta_cache
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
                task = _task(raw)

                def compute():
                    _, record, failed, _ = plan_task(
                        self.scenario,
                        self.router,
                        task,
                        vehicle["id"],
                        position,
                        start,
                        vertices,
                        edges,
                    )
                    return float("inf") if failed else record["delivery_end"]

                if self.eta_cache is None:
                    estimates[key] = compute()
                else:
                    query = (
                        self.router.geometry,
                        vehicle["id"],
                        position,
                        start,
                        task,
                        tuple(self.scenario.pickup_candidates(task)),
                    )
                    # SIPP never examines reservations before this departure;
                    # retaining the absolute suffix permits exact cross-tick reuse.
                    signature = (
                        frozenset(v for v in vertices if v[0] >= start),
                        frozenset(e for e in edges if e[0] >= start),
                    )
                    estimates[key] = self.eta_cache.get_or_compute(query, signature, compute)
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
