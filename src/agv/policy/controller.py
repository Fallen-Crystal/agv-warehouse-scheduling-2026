"""Observation-only policy stages and historical result adapters.

Stages decide; the runner commits. In particular, idle positioning and joint
repair consume a fresh observation after assignment has been committed. Their
ordering is part of the historical execution contract.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from agv.policy.bcrd import bcrd_action

Observation = Mapping[str, Any]
Pair = tuple[int, int]


@dataclass
class PolicyContext:
    decisions: list[dict] = field(default_factory=list)
    observed_tasks: set[int] = field(default_factory=set)
    position_attempts: int = 0
    position_rejections: int = 0
    replan_calls: int = 0


class AssignStage(Protocol):
    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]: ...


class IdleStage(Protocol):
    def observe(self, observation: Observation, context: PolicyContext) -> None: ...

    def due(self, observation: Observation) -> bool: ...

    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]: ...


class RepairStage(Protocol):
    def due(self, time: int, feedback: list[dict]) -> bool: ...

    def decide(self, observation: Observation, context: PolicyContext) -> dict | None: ...


class Reporter(Protocol):
    def finish(self, result: dict, context: PolicyContext) -> dict: ...


@dataclass(frozen=True)
class Controller:
    assign: AssignStage
    reporter: Reporter
    idle: IdleStage | None = None
    repair: RepairStage | None = None
    capture_errors: bool = False
    track_observed_tasks: bool = False

    def observe(self, observation: Observation, context: PolicyContext) -> None:
        if self.track_observed_tasks:
            context.observed_tasks.update(j["id"] for j in observation["pending"])
            context.observed_tasks.update(
                v["task_id"] for v in observation["vehicles"] if v["task_id"] is not None
            )
        if self.idle:
            self.idle.observe(observation, context)


@dataclass(frozen=True)
class CallableAssignment:
    action: Callable

    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]:
        return self.action(observation)


@dataclass(frozen=True)
class RolloutAssignment:
    options: Mapping[str, Any]
    world_factory: Callable

    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]:
        return bcrd_action(
            observation,
            diagnostics=context.decisions,
            world_factory=self.world_factory,
            **self.options,
        )


@dataclass(frozen=True)
class EtaAssignment:
    matcher: Any

    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]:
        return self.matcher.action(observation)


@dataclass(frozen=True)
class PositioningIdle:
    locator: Any

    def observe(self, observation: Observation, context: PolicyContext) -> None:
        self.locator.observe(observation)

    def due(self, observation: Observation) -> bool:
        return not observation["order_stream_closed"] and (
            observation["time"] - self.locator.last >= self.locator.interval
            or self.locator.new_idle
        )

    def decide(self, observation: Observation, context: PolicyContext) -> list[Pair]:
        return self.locator.action(observation)


@dataclass(frozen=True)
class JointRepair:
    planner: Any
    interval: int
    enabled: bool

    def due(self, time: int, feedback: list[dict]) -> bool:
        return self.enabled and (time % self.interval == 0 or any(f["accepted"] for f in feedback))

    def decide(self, observation: Observation, context: PolicyContext) -> dict | None:
        context.replan_calls += 1
        return self.planner.propose(observation)


@dataclass(frozen=True)
class BaselineReporter:
    def finish(self, result: dict, context: PolicyContext) -> dict:
        return result


@dataclass(frozen=True)
class OptimizedReporter:
    assignment: str
    joint: bool
    interval: int
    attempts: int
    router_kind: str
    neighborhoods: str
    trial_budget: int | None
    ranker: Any
    planner: Any

    def finish(self, result: dict, context: PolicyContext) -> dict:
        result["joint_routing_stats"] = (
            dict(self.planner.router.stats)
            if self.planner.router
            else dict(calls=0, expanded=0, generated=0)
        )
        result["algorithm"] = dict(
            assignment=self.assignment,
            joint=self.joint,
            interval=self.interval,
            attempts=self.attempts,
            router=self.router_kind,
            neighborhoods=self.neighborhoods,
            trial_budget=self.trial_budget,
            learned_ranker=self.ranker is not None,
            replan_calls=context.replan_calls,
            accepted_replans=len(result["replanning_events"]),
        )
        return result


@dataclass(frozen=True)
class StreamReporter:
    matcher: Any
    locator: Any
    positioning: bool
    delay: bool

    def finish(self, result: dict, context: PolicyContext) -> dict:
        result["algorithm"] = dict(
            assignment="eta_matching" if self.matcher else "greedy",
            router="sipp",
            joint=False,
            positioning=self.positioning,
            delay=self.delay,
            position_attempts=context.position_attempts,
            position_rejections=context.position_rejections,
        )
        result["dispatch_decisions"] = self.matcher.log if self.matcher else []
        if self.matcher:
            result["decision_routing_stats"] = dict(self.matcher.router.stats)
            result["algorithm"].update(
                delay_max_wait=self.matcher.max_wait, delay_threshold=self.matcher.threshold
            )
        if self.locator:
            result["algorithm"]["positioning_parameters"] = dict(
                strength=self.locator.strength,
                sigma=self.locator.sigma,
                interval=self.locator.interval,
                capacity=self.locator.capacity,
                hysteresis=self.locator.hysteresis,
                history_decay_steps=200,
            )
        return result


@dataclass(frozen=True)
class DispatchReporter:
    policy: str
    max_batches: int
    depth: int | None
    mode: str
    min_queue_ratio: float
    event_driven: bool
    idle_hold_steps: int
    tail_guard: bool

    def finish(self, result: dict, context: PolicyContext) -> dict:
        result["algorithm"] = dict(
            assignment=self.policy,
            joint=False,
            router="sipp",
            replan_calls=0,
            accepted_replans=0,
            max_batches=self.max_batches if self.policy == "bcrd" else 0,
            depth=self.depth,
            candidate_mode=self.mode,
            min_queue_ratio=self.min_queue_ratio,
            event_driven=self.event_driven,
        )
        if self.idle_hold_steps:
            result["algorithm"]["idle_hold_steps"] = self.idle_hold_steps
        if self.tail_guard:
            result["algorithm"]["tail_guard"] = "visible_rollout_p90_not_worse_than_greedy"
        result["observed_task_count"] = len(context.observed_tasks)
        meaningful = [row for row in context.decisions if row["candidates"] or row["issued_pairs"]]
        result["dispatch_decisions"] = meaningful
        result["dispatch_stats"] = dict(
            decisions=len(meaningful),
            searched=sum(bool(row["candidates"]) for row in meaningful),
            changed=sum(row["chosen"] != "greedy" for row in meaningful),
            fallbacks=sum(row["fallback"] for row in meaningful),
            shadow_calls=sum(row["shadow_calls"] for row in meaningful),
            shadow_route_calls=sum(row["shadow_route_calls"] for row in meaningful),
            shadow_expanded=sum(row["shadow_expanded"] for row in meaningful),
            decision_cpu_seconds=sum(row["cpu_seconds"] for row in context.decisions),
        )
        return result
