"""Observation-only, disposable previews using the real execution semantics.

The shadow owns an Environment reconstructed from *released* pending/active
jobs and committed suffixes. It never receives a real Environment or its full
Scenario. Completed history is a candidate-independent constant and is omitted;
returning vehicles still reserve their entire observed return suffix.
"""

from copy import deepcopy
from dataclasses import asdict
from time import process_time

from agv.dispatch.greedy import greedy_action
from agv.domain import Scenario, Task
from agv.simulation import Environment


class _BudgetExceeded(Exception):
    pass


class _VisibleEnvironment(Environment):
    """Retain observed historical metadata without inventing completed Task data.

    Completed records no longer hold pickup locks. They are exposed unchanged
    to rollout policies, but excluded from the variable candidate objective.
    """

    def observe(self):
        observation = super().observe()
        history = getattr(self, "_visible_completed", [])
        observation["completed"] = deepcopy(history) + observation["completed"]
        old_routes = getattr(self, "_visible_old_routes", {})
        for vehicle in observation["vehicles"]:
            if vehicle["route_record"] is None and vehicle["id"] in old_routes:
                vehicle["route_record"] = deepcopy(old_routes[vehicle["id"]])
        return observation


class _BudgetedRouter:
    """Count/check real leg calls without duplicating or weakening a planner.

    Route-call limits are hard. CPU/expansion limits are checked at leg
    boundaries, so at most one real leg can exceed those soft limits.
    """

    def __init__(self, router, budget, started):
        self._router = router
        self._budget = budget
        self._started = started

    def __getattr__(self, name):
        return getattr(self._router, name)

    def check(self):
        if self.stats["calls"] >= self._budget.get("max_route_calls", float("inf")):
            raise _BudgetExceeded("route_calls")
        if self.stats["expanded"] >= self._budget.get("max_expanded", float("inf")):
            raise _BudgetExceeded("expanded")
        if process_time() - self._started >= self._budget.get("max_cpu_seconds", float("inf")):
            raise _BudgetExceeded("cpu")

    def leg(self, *args, **kwargs):
        self.check()
        result = self._router.leg(*args, **kwargs)
        # Equality is allowed for a completed final call, unlike the pre-call
        # guard; exceeding a soft limit discards this candidate entirely.
        if self.stats["expanded"] > self._budget.get("max_expanded", float("inf")):
            raise _BudgetExceeded("expanded")
        if process_time() - self._started > self._budget.get("max_cpu_seconds", float("inf")):
            raise _BudgetExceeded("cpu")
        return result


def _task(raw):
    fields = {key: raw[key] for key in Task.__dataclass_fields__ if key in raw}
    for name in ("pickup", "delivery", "shelf"):
        if fields.get(name) is not None:
            fields[name] = tuple(fields[name])
    return Task(**fields)


def _safe_greedy(observation):
    """Keep the legacy greedy order, legalizing same-face batch capacity."""
    if not any(vehicle["available"] for vehicle in observation["vehicles"]) or not any(
        job.get("dispatchable", True) for job in observation["pending"]
    ):
        return []
    pending = {job["id"]: job for job in observation["pending"]}
    v4 = observation["map"].get("map_info", {}).get("model_version") == "math-v4-integrated"
    faces, pairs = set(), []
    for vehicle, job in greedy_action(observation):
        face = tuple(pending[job]["shelf"]) if pending[job].get("shelf") else None
        if v4 and face in faces:
            continue
        faces.add(face)
        pairs.append((vehicle, job))
    return pairs


def _budget_values(budget):
    values = {} if budget is None else dict(budget)
    allowed = {"max_steps", "max_route_calls", "max_expanded", "max_cpu_seconds"}
    if set(values) - allowed:
        raise ValueError("Unknown shadow budget field")
    for key, value in values.items():
        if key == "max_cpu_seconds":
            if type(value) not in (int, float) or value < 0 or value != value:
                raise ValueError("Invalid CPU budget")
        elif type(value) is not int or value < 0:
            raise ValueError("Shadow count budgets must be nonnegative integers")
    # Protect unbounded scenarios and ill-behaved user-supplied rollout policies.
    values.setdefault("max_steps", 10000)
    return values


class ShadowState:
    """An immutable visible snapshot; each preview starts a fresh disposable replay.

    ``depth=None`` rolls out all known jobs. ``depth=0`` only submits the given
    batch. ``depth=n`` permits at most n additional nonempty dispatch batches.
    Truncated previews retain exact committed completion predictions and report
    every unassigned known job as residual; they never count residuals as done.
    ``paths`` starts at the observation time, and contains executed preview
    positions plus any still-committed suffix (including all returns).

    Event-driven replay skips only provably empty default-policy decisions;
    ``event_driven=False`` retains the reference one-step replay. Custom
    rollout policies always receive every time step. Counting budgets retain
    identical results; a CPU cutoff can occur at different times because the
    two implementations intentionally perform different amounts of work.
    """

    def __init__(self, observation, router_kind, event_driven=True):
        if type(event_driven) is not bool:
            raise ValueError("event_driven must be a boolean")
        self._event_driven = event_driven
        self._observation = deepcopy(observation)
        self._router_kind = router_kind
        self._scenario, self._active_records = self._visible_scenario()

    @classmethod
    def from_observation(cls, observation, router_kind="sipp", event_driven=True):
        if router_kind not in ("astar", "sipp"):
            raise ValueError("router must be 'astar' or 'sipp'")
        return cls(observation, router_kind, event_driven)

    def _visible_scenario(self):
        obs = self._observation
        now = obs.get("time")
        if type(now) is not int or now < 0:
            raise ValueError("Invalid observation time")
        scenario = Scenario.from_observation_map(obs["map"], obs["horizon"])
        vehicles = obs["vehicles"]
        if [v["id"] for v in vehicles] != list(range(len(scenario.homes))):
            raise ValueError("Observation must contain every vehicle in ID order")
        jobs, records = {}, []
        for raw in obs["pending"]:
            job = _task(raw)
            if job.id in jobs or job.release > now:
                raise ValueError("Duplicate or unreleased visible task")
            jobs[job.id] = job
        for vehicle in vehicles:
            active = vehicle.get("active_task")
            record = vehicle.get("route_record")
            if vehicle["available"]:
                if active is not None or vehicle.get("task_id") is not None:
                    raise ValueError("Available vehicle cannot own an active task")
            else:
                if active is None or record is None:
                    raise ValueError("Busy vehicle requires its visible task and commitment")
                job = _task(active)
                if (
                    job.id in jobs
                    or job.release > now
                    or record["task_id"] != job.id
                    or vehicle["task_id"] != job.id
                    or record["vehicle"] != vehicle["id"]
                    or record["delivery_end"] <= now
                ):
                    raise ValueError("Inconsistent active task commitment")
                jobs[job.id] = job
                records.append(deepcopy(record))
            path = vehicle["return_path"] if vehicle["available"] else vehicle["committed_path"]
            if not path or tuple(path[0]) != tuple(vehicle["position"]):
                raise ValueError("Committed suffix must start at current position")
            if tuple(path[-1]) != scenario.homes[vehicle["id"]]:
                raise ValueError("Committed suffix must end at its own home")
        # Preserve the original visible pending order, which is part of the
        # observation contract; no hidden order/seed/normalization is supplied.
        scenario.tasks = list(jobs.values())
        return scenario.check(), records

    def _environment(self, budget, started):
        env = _VisibleEnvironment(self._scenario, router_kind=self._router_kind)
        obs = self._observation
        env.time = obs["time"]
        env._visible_completed = deepcopy(obs.get("completed", []))
        env._visible_old_routes = {
            vehicle["id"]: deepcopy(vehicle["route_record"])
            for vehicle in obs["vehicles"]
            if vehicle["available"] and vehicle.get("route_record") is not None
        }
        env._plans = [
            [tuple(p) for p in (v["return_path"] if v["available"] else v["committed_path"])]
            for v in obs["vehicles"]
        ]
        env._paths = [[path[0]] for path in env._plans]
        env._interval_states = [[] for _ in env._plans]
        env._records = deepcopy(self._active_records)
        env._assigned = {record["task_id"] for record in env._records}
        active = {record["vehicle"]: record for record in env._records}
        env._active = [active.get(k) for k in range(len(env._plans))]
        env._router = _BudgetedRouter(env._router, budget, started)
        return env

    def preview(self, ordered_batch, depth=None, rollout_policy=None, budget=None):
        if depth is not None and (type(depth) is not int or depth < 0):
            raise ValueError("depth must be None or a nonnegative integer")
        limits = _budget_values(budget)
        started = process_time()
        env = self._environment(limits, started)
        origin = env.time
        feedback, rounds, reason, exhausted = [], 0, None, False
        policy = _safe_greedy if rollout_policy is None else rollout_policy
        try:
            if limits.get("max_cpu_seconds", float("inf")) <= 0:
                raise _BudgetExceeded("cpu")
            feedback = env.assign(ordered_batch)
            if not all(item["accepted"] for item in feedback):
                reason = "initial_route_failure"
            elif depth != 0:
                while not env.done and (
                    env._scenario.horizon is None or env.time < env._scenario.horizon
                ):
                    if env.time - origin >= limits["max_steps"]:
                        raise _BudgetExceeded("steps")
                    if process_time() - started >= limits.get("max_cpu_seconds", float("inf")):
                        raise _BudgetExceeded("cpu")
                    # Only the known default policy has provably empty actions
                    # while all cars are busy, or after all visible jobs have
                    # been assigned. Preserve the final one-step depth break,
                    # and never skip returning-car positions when work remains.
                    steps = 1
                    if (
                        self._event_driven
                        and rollout_policy is None
                        and (depth is None or rounds < depth)
                    ):
                        if len(env._assigned) == len(env._jobs):
                            steps = max(map(len, env._plans)) - 1
                        elif all(record is not None for record in env._active):
                            steps = min(record["delivery_end"] for record in env._active) - env.time
                        steps = min(steps, limits["max_steps"] - (env.time - origin))
                        if env._scenario.horizon is not None:
                            steps = min(steps, env._scenario.horizon - env.time)
                    # Real advance still records every intermediate position,
                    # service label, and exact delivery release; only empty
                    # observation/policy/assignment calls are skipped.
                    env.advance(steps, observe=False)
                    if env.done or (
                        env._scenario.horizon is not None and env.time >= env._scenario.horizon
                    ):
                        break
                    if depth is not None and rounds >= depth:
                        break
                    action = policy(env.observe())
                    later = env.assign(action)
                    if action:
                        rounds += 1
                    if env.stop_if_stalled(later):
                        reason = "rollout_stalled"
                        break
        except _BudgetExceeded as error:
            reason, exhausted = "budget_" + str(error), True
        except (ValueError, TypeError, KeyError) as error:
            reason = "invalid_action:" + str(error)
        records = deepcopy(env._records)
        jobs = env._jobs
        flows = [record["delivery_end"] - jobs[record["task_id"]].release for record in records]
        paths = [past + plan[1:] for past, plan in zip(env._paths, env._plans)]
        moves = sum(a != b for path in paths for a, b in zip(path, path[1:]))
        residual = [asdict(job) for job in jobs.values() if job.id not in env._assigned]
        completed = not residual and len(records) == len(jobs)
        if not completed and reason is None:
            reason = "depth_limited" if depth is not None else "horizon_exhausted"
        return dict(
            valid=reason is None or reason == "depth_limited",
            completed=completed,
            exhausted=exhausted,
            reason=reason,
            feedback=feedback,
            assignments=records,
            paths=paths,
            predicted_T=max((record["delivery_end"] for record in records), default=origin),
            flow_sum=sum(flows),
            mean_flow_time=sum(flows) / len(flows) if flows else 0,
            flow_times=flows,
            additional_moves=moves,
            residual_count=len(residual),
            residual_tasks=residual,
            visible_task_count=len(jobs),
            simulated_steps=env.time - origin,
            decision_rounds=rounds,
            routing_stats=deepcopy(env._router.stats),
            planning_failures=deepcopy(env._planning_failures),
            cpu_seconds=process_time() - started,
        )
