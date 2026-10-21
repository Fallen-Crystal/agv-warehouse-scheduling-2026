"""Reconstruct disposable worlds from public observations only.

Factories supply execution services and any compatibility wrapper. This module
never imports a planner, policy, evaluator, or application composition root.
Hydration is a kernel operation; rollout policy never writes private state.
"""

from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache

from agv.world.itinerary import Itinerary


class VisibleWorldMixin:
    """Visible-history projection over the existing execution kernel.

    Completed task identities need not be reconstructed: their past records
    are constant across candidates and do not hold pickup locks. They remain
    visible to rollout policies while the forecast measures variable work only.
    """

    def observe(self):
        observation = super().observe()
        history = getattr(self, "_visible_completed", [])
        observation["completed"] = deepcopy(history) + observation["completed"]
        old_routes = getattr(self, "_visible_old_routes", {})
        for record in observation["completed"]:
            old = old_routes.get(record["vehicle"])
            if old is not None and old["task_id"] == record["task_id"]:
                record.update(return_end=old["return_end"], return_arrival=old["return_arrival"])
        if "completed_flow_times" in observation:
            observation["completed_flow_times"] = (
                list(getattr(self, "_historical_flow_times", []))
                + observation["completed_flow_times"]
            )
        for vehicle in observation["vehicles"]:
            if vehicle["route_record"] is None and vehicle["id"] in old_routes:
                vehicle["route_record"] = deepcopy(old_routes[vehicle["id"]])
        return observation

    @property
    def forecast_can_advance(self):
        return not self.done and (
            self._scenario.horizon is None or self.time < self._scenario.horizon
        )

    @property
    def forecast_released_complete(self):
        return len(self._assigned) == len(self._jobs) and all(
            record is None for record in self._active
        )

    def forecast_steps(self, origin, max_steps, *, open_stream, skip_empty):
        """Find a safe skip over empty decisions without implementing a tick."""
        steps = 1
        if skip_empty:
            if len(self._assigned) == len(self._jobs):
                steps = (
                    min(record["delivery_end"] for record in self._active if record is not None)
                    - self.time
                    if open_stream and any(record is not None for record in self._active)
                    else max(map(len, self._plans)) - 1
                )
            elif all(record is not None for record in self._active):
                steps = min(record["delivery_end"] for record in self._active) - self.time
            elif not any(
                job.id not in self._assigned
                and self.ruleset.dispatchable(job, self._records, self._assigned, self.time)[0]
                for job in self._jobs.values()
            ):
                # This visible world contains no unreleased jobs. With no legal
                # order, default/stateless-priority policies emit nothing until
                # a pickup lock or active delivery changes. Still record EVERY
                # intermediate physical tick through advance().
                events = [
                    r[key]
                    for r in self._active
                    if r is not None
                    for key in ("pickup_end", "delivery_end")
                    if r[key] > self.time
                ]
                if events:
                    steps = min(events) - self.time
            steps = min(steps, max_steps - (self.time - origin))
            if self._scenario.horizon is not None:
                steps = min(steps, self._scenario.horizon - self.time)
        return steps

    def forecast_result(
        self,
        origin,
        *,
        open_stream,
        reason,
        feedback,
        exhausted,
        depth,
        decision_rounds,
    ):
        """Return detached forecast measurements without exposing kernel fields."""
        records = deepcopy(self._records)
        jobs = self._jobs
        flows = [record["delivery_end"] - jobs[record["task_id"]].release for record in records]
        paths = [past + plan[1:] for past, plan in zip(self._paths, self._plans)]
        if open_stream:
            # No fabricated close event and no charge for unexecuted final returns.
            end = max([origin] + [record["delivery_end"] for record in records])
            paths = [path[: end - origin + 1] for path in paths]
        moves = sum(a != b for path in paths for a, b in zip(path, path[1:]))
        residual = [asdict(job) for job in jobs.values() if job.id not in self._assigned]
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
            simulated_steps=self.time - origin,
            decision_rounds=decision_rounds,
            routing_stats=deepcopy(self._router.stats),
            planning_failures=deepcopy(self._planning_failures),
        )


@lru_cache(maxsize=8)
def _visible_world_type(world_factory):
    """Project observations without importing an upper-layer world factory."""
    return type("VisibleWorld", (VisibleWorldMixin, world_factory), {})


def reconstruct_visible_world(
    observation,
    scenario,
    active_records,
    router_kind,
    budget_router_factory,
    *,
    world_factory,
):
    """Restore only released work and committed suffixes into a fresh kernel.

    ``scenario`` must be the detached visible scene validated by the caller.
    ``world_factory`` is an injected WorldState class with execution services;
    the historical Environment facade is supported without a reverse import.
    """
    world = _visible_world_type(world_factory)(
        scenario, router_kind=router_kind, stream_open=scenario.is_v9_1
    )
    world.time = observation["time"]
    world._visible_completed = deepcopy(observation.get("completed", []))
    world._visible_old_routes = {
        vehicle["id"]: deepcopy(vehicle["route_record"])
        for vehicle in observation["vehicles"]
        if vehicle["available"] and vehicle.get("route_record") is not None
    }
    world._plans = [
        Itinerary(
            tuple(point)
            for point in (
                vehicle["return_path"] if vehicle["available"] else vehicle["committed_path"]
            )
        )
        for vehicle in observation["vehicles"]
    ]
    world._paths = [[plan[0]] for plan in world._plans]
    world._interval_states = [[] for _ in world._plans]
    world._records = deepcopy(active_records)
    world._assigned = {record["task_id"] for record in world._records}
    active = {record["vehicle"]: record for record in world._records}
    world._active = [active.get(vehicle) for vehicle in range(len(world._plans))]
    if scenario.is_v9_1:
        world._idle_hold_counts = list(observation.get("idle_hold_counts", world._idle_hold_counts))
        world._idle_waits = deepcopy(observation.get("idle_waits", []))
        world._historical_flow_times = list(observation.get("completed_flow_times", []))
        world._released_jobs = dict(world._jobs)
        world._stream_closed = observation["order_stream_closed"]
        world._stream_closed_at = observation["stream_closed_at"]
    world._router = budget_router_factory(world._router)
    return world
