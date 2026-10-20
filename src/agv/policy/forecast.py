"""Observation-only, disposable previews using the real execution semantics.

The shadow owns an Environment reconstructed from *released* pending/active
jobs and committed suffixes. It never receives a real Environment or its full
Scenario. Completed history is a candidate-independent constant and is omitted;
returning vehicles still reserve their entire observed return suffix.
"""

from copy import deepcopy
from time import process_time

from agv.core import Task
from agv.policy.greedy import greedy_action
from agv.warehouse.scenarios import Scenario
from agv.world.restore import reconstruct_visible_world


class _BudgetExceeded(Exception):
    pass


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
    v4 = observation["map"].get("map_info", {}).get("model_version") in (
        "math-v4-integrated",
        "mixed-v9",
    )
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

    def __init__(self, observation, router_kind, event_driven=True, *, world_factory):
        if type(event_driven) is not bool:
            raise ValueError("event_driven must be a boolean")
        self._event_driven = event_driven
        self._observation = deepcopy(observation)
        self._router_kind = router_kind
        self._world_factory = world_factory
        self._scenario, self._active_records = self._visible_scenario()

    @classmethod
    def from_observation(cls, observation, router_kind="sipp", event_driven=True, *, world_factory):
        if router_kind not in ("astar", "sipp"):
            raise ValueError("router must be 'astar' or 'sipp'")
        return cls(observation, router_kind, event_driven, world_factory=world_factory)

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
        if scenario.is_v9_1:
            if type(obs.get("order_stream_closed")) is not bool:
                raise ValueError("Missing stream state")
            closed_at = obs.get("stream_closed_at")
            if obs["order_stream_closed"]:
                if (
                    type(closed_at) is not int
                    or not max((j.release for j in scenario.tasks), default=0) <= closed_at <= now
                ):
                    raise ValueError("Invalid observed close event")
            elif closed_at is not None:
                raise ValueError("Open stream cannot disclose a future close event")
            scenario.order_stream_end = (
                closed_at
                if obs["order_stream_closed"]
                else max((j.release for j in scenario.tasks), default=0)
            )
        return scenario.check(), records

    def _environment(self, budget, started):
        return reconstruct_visible_world(
            self._observation,
            self._scenario,
            self._active_records,
            self._router_kind,
            lambda router: _BudgetedRouter(router, budget, started),
            world_factory=self._world_factory,
        )

    def preview(self, ordered_batch, depth=None, rollout_policy=None, budget=None):
        if depth is not None and (type(depth) is not int or depth < 0):
            raise ValueError("depth must be None or a nonnegative integer")
        limits = _budget_values(budget)
        started = process_time()
        env = self._environment(limits, started)
        origin = env.time
        feedback, rounds, reason, exhausted = [], 0, None, False
        policy = _safe_greedy if rollout_policy is None else rollout_policy
        open_stream = self._scenario.is_v9_1 and not self._observation["order_stream_closed"]
        try:
            if limits.get("max_cpu_seconds", float("inf")) <= 0:
                raise _BudgetExceeded("cpu")
            feedback = env.assign(ordered_batch)
            if not all(item["accepted"] for item in feedback):
                reason = "initial_route_failure"
            elif depth != 0:
                while env.forecast_can_advance:
                    if open_stream and env.forecast_released_complete:
                        break
                    if env.time - origin >= limits["max_steps"]:
                        raise _BudgetExceeded("steps")
                    if process_time() - started >= limits.get("max_cpu_seconds", float("inf")):
                        raise _BudgetExceeded("cpu")
                    # Only the known default policy has provably empty actions
                    # while all cars are busy, or after all visible jobs have
                    # been assigned. Preserve the final one-step depth break,
                    # and never skip returning-car positions when work remains.
                    steps = env.forecast_steps(
                        origin,
                        limits["max_steps"],
                        open_stream=open_stream,
                        skip_empty=(
                            self._event_driven
                            and rollout_policy is None
                            and (depth is None or rounds < depth)
                        ),
                    )
                    # Real advance still records every intermediate position,
                    # service label, and exact delivery release; only empty
                    # observation/policy/assignment calls are skipped.
                    env.advance(steps, observe=False)
                    if not env.forecast_can_advance:
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
        result = env.forecast_result(
            origin,
            open_stream=open_stream,
            reason=reason,
            feedback=feedback,
            exhausted=exhausted,
            depth=depth,
            decision_rounds=rounds,
        )
        result["cpu_seconds"] = process_time() - started
        return result
