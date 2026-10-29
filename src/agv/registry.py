"""Typed solver compositions and their historical public names.

This is the composition root: named configurations select independent policy
stages, their routing implementation and the profiles they support. Imports of
concrete policy implementations stay inside ``build_controller`` so the pure
specification data does not create dependencies back into the execution loop.
"""

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Literal

from agv.core import Profile

HISTORICAL_PROFILES: frozenset[Profile] = frozenset((Profile.LEGACY, Profile.V4, Profile.V9))
STREAM_PROFILES: frozenset[Profile] = frozenset((Profile.V91,))
ALL_PROFILES = HISTORICAL_PROFILES | STREAM_PROFILES


@dataclass(frozen=True)
class AssignSpec:
    kind: Literal["greedy", "matching", "eta_matching", "bcrd"] = "greedy"
    delay: bool = False
    max_batches: int = 4
    depth: int | None = None
    mode: str = "full"
    min_queue_ratio: float = 3.0
    event_driven: bool = True
    tail_guard: bool = False
    eta_cache_capacity: int = 0
    route_budget: int | None = None
    expansion_budget: int | None = None
    step_budget: int | None = None

    def __post_init__(self):
        if self.kind not in ("greedy", "matching", "eta_matching", "bcrd"):
            raise ValueError("Unknown assignment kind")
        for name in ("delay", "event_driven", "tail_guard"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if type(self.max_batches) is not int or not 0 <= self.max_batches <= 32:
            raise ValueError("max_batches must be 0..32")
        if self.depth is not None and (type(self.depth) is not int or self.depth < 0):
            raise ValueError("depth must be a nonnegative integer or None")
        if self.mode not in ("full", "order"):
            raise ValueError("Unknown candidate mode")
        if (
            type(self.min_queue_ratio) not in (int, float)
            or not isfinite(self.min_queue_ratio)
            or self.min_queue_ratio < 0
        ):
            raise ValueError("min_queue_ratio must be finite and nonnegative")
        if type(self.eta_cache_capacity) is not int or self.eta_cache_capacity < 0:
            raise ValueError("eta_cache_capacity must be a nonnegative integer")
        if self.eta_cache_capacity and self.kind != "eta_matching":
            raise ValueError("ETA caching requires eta_matching")
        for name in ("route_budget", "expansion_budget", "step_budget"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
            if value is not None and self.kind != "bcrd":
                raise ValueError("Rollout budgets require bcrd")
        if self.delay and self.kind != "eta_matching":
            raise ValueError("Delayed assignment requires eta_matching")
        if self.kind != "bcrd" and (
            self.tail_guard
            or self.max_batches != 4
            or self.depth is not None
            or self.mode != "full"
            or self.min_queue_ratio != 3.0
            or not self.event_driven
        ):
            raise ValueError("Rollout options require bcrd")


@dataclass(frozen=True)
class IdleSpec:
    kind: Literal["profile", "standby", "positioning"] = "profile"
    hold_steps: int = 0
    stat_window: int | None = None
    rebalance_period: int | None = None
    hotspot_zones: int = 0
    protect_utilization: float | None = None

    def __post_init__(self):
        if self.kind not in ("profile", "standby", "positioning"):
            raise ValueError("Unknown idle kind")
        if type(self.hold_steps) is not int or self.hold_steps < 0:
            raise ValueError("hold_steps must be a nonnegative integer")
        if self.hold_steps and self.kind != "standby":
            raise ValueError("hold_steps requires standby")
        for name in ("stat_window", "rebalance_period"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer or None")
        if type(self.hotspot_zones) is not int or self.hotspot_zones < 0:
            raise ValueError("hotspot_zones must be a nonnegative integer")
        if self.protect_utilization is not None and (
            type(self.protect_utilization) not in (int, float)
            or not isfinite(self.protect_utilization)
            or not 0 < self.protect_utilization <= 1
        ):
            raise ValueError("protect_utilization must be greater than zero and at most one")
        if self.kind != "positioning" and any(
            value is not None
            for value in (self.stat_window, self.rebalance_period, self.protect_utilization)
        ):
            raise ValueError("Positioning options require positioning")
        if self.kind != "positioning" and self.hotspot_zones:
            raise ValueError("Positioning options require positioning")


@dataclass(frozen=True)
class RepairSpec:
    enabled: bool = True
    interval: int = 5
    attempts: int = 8
    neighborhoods: str = "legacy"
    trial_budget: int | None = None
    learned: bool = False


@dataclass(frozen=True)
class SolverSpec:
    router: Literal["astar", "sipp"] = "astar"
    assign: AssignSpec = field(default_factory=AssignSpec)
    idle: IdleSpec = field(default_factory=IdleSpec)
    repair: RepairSpec | None = None
    profiles: frozenset[Profile] = ALL_PROFILES
    result_style: Literal["baseline", "optimized", "dispatch", "stream"] = "baseline"

    def __post_init__(self):
        if self.router not in ("astar", "sipp"):
            raise ValueError("Unknown router")
        if not self.profiles or not all(isinstance(p, Profile) for p in self.profiles):
            raise ValueError("profiles must contain explicit Profile values")
        if self.assign.kind == "bcrd" and (self.idle.kind == "positioning" or self.idle.hold_steps):
            raise ValueError("BCRD standby needs a separately validated shadow contract")

        supported = {
            "baseline": ("greedy",),
            "optimized": ("greedy", "matching"),
            "dispatch": ("greedy", "matching", "bcrd"),
            "stream": ("greedy", "eta_matching"),
        }
        if (
            self.result_style not in supported
            or self.assign.kind not in supported[self.result_style]
        ):
            raise ValueError("Assignment stage is incompatible with result_style")
        if self.assign.delay and self.assign.kind != "eta_matching":
            raise ValueError("Delayed assignment requires eta_matching")
        if self.idle.kind == "positioning" and self.result_style != "stream":
            raise ValueError("Positioning stage requires the stream result_style")
        if self.repair is not None and self.result_style != "optimized":
            raise ValueError("Repair stage requires the optimized result_style")
        if self.result_style in ("dispatch", "stream") and self.router != "sipp":
            raise ValueError("Dispatch and stream result styles require the SIPP router")


def _optimized(assignment="greedy", *, joint=True, router="astar", **repair):
    return SolverSpec(
        router=router,
        assign=AssignSpec(kind=assignment),
        repair=RepairSpec(enabled=joint, **repair),
        profiles=HISTORICAL_PROFILES,
        result_style="optimized",
    )


def _dispatch(policy="greedy", *, idle_hold_steps=0, **assignment):
    return SolverSpec(
        router="sipp",
        assign=AssignSpec(kind=policy, **assignment),
        idle=IdleSpec(kind="standby" if idle_hold_steps else "profile", hold_steps=idle_hold_steps),
        profiles=frozenset((Profile.V9,)) if idle_hold_steps else HISTORICAL_PROFILES,
        result_style="dispatch",
    )


def _stream(policy="eta_matching", *, positioning=False, **assignment):
    return SolverSpec(
        router="sipp",
        assign=AssignSpec(kind=policy, **assignment),
        idle=IdleSpec(kind="positioning" if positioning else "profile"),
        profiles=STREAM_PROFILES,
        result_style="dispatch" if policy == "bcrd" else "stream",
    )


# Order is public: argparse choices, UI options and archived experiment configs
# retain their previous iteration order. Assignment kinds never contain names.
SOLVERS: dict[str, SolverSpec] = {
    "baseline": SolverSpec(),
    "matching_only": _optimized("matching", joint=False),
    "joint_only": _optimized(),
    "matching_joint": _optimized("matching"),
    "sipp_joint": _optimized(router="sipp"),
    "sipp_conflict": _optimized(router="sipp", neighborhoods="conflict"),
    "sipp_budget": _optimized(router="sipp", neighborhoods="conflict", trial_budget=6),
    "sipp_matching": _optimized(
        "matching", router="sipp", neighborhoods="conflict", trial_budget=6
    ),
    "sipp_learned": _optimized(
        router="sipp", neighborhoods="conflict", trial_budget=6, learned=True
    ),
    # This old alias historically used the dispatch result schema, including
    # observed_task_count, rather than stream.run's positioning schema.
    "sipp_stream_dispatch": SolverSpec(
        router="sipp", profiles=STREAM_PROFILES, result_style="dispatch"
    ),
    "sipp_greedy_dispatch": _dispatch(),
    "sipp_matching_dispatch": _dispatch("matching"),
    "bcrd_budget": _dispatch("bcrd"),
    "bcrd_order": _dispatch("bcrd", mode="order"),
    "sipp_standby8_dispatch": _dispatch(idle_hold_steps=8),
    "sipp_standby16_dispatch": _dispatch(idle_hold_steps=16),
    "sipp_standby32_dispatch": _dispatch(idle_hold_steps=32),
    "sipp_stream_matching": _stream(),
    "sipp_position_dispatch": _stream("greedy", positioning=True),
    "sipp_position_matching_dispatch": _stream(positioning=True),
    "sipp_position_delay_dispatch": _stream(positioning=True, delay=True),
    "sipp_stream_bcrd": _stream("bcrd"),
    "sipp_stream_bcrd_tail": _stream("bcrd", tail_guard=True),
}


def _dispatch_parameters(spec):
    params = dict(policy=spec.assign.kind)
    if spec.assign.kind == "bcrd":
        params["max_batches"] = spec.assign.max_batches
        if spec.assign.mode != "full":
            params["mode"] = spec.assign.mode
    if spec.idle.hold_steps:
        params["idle_hold_steps"] = spec.idle.hold_steps
    return params


# Compatibility views are derived from SOLVERS; they are not registration
# tables and are never consulted by the execution dispatcher.
DISPATCH_SOLVERS = {
    name: _dispatch_parameters(spec)
    for name, spec in SOLVERS.items()
    if spec.result_style == "dispatch" and name not in ("sipp_stream_bcrd", "sipp_stream_bcrd_tail")
}
STREAM_SOLVERS = {
    name: (
        dict(policy="bcrd", **(dict(tail_guard=True) if spec.assign.tail_guard else {}))
        if spec.assign.kind == "bcrd"
        else dict(
            policy="matching" if spec.assign.kind == "eta_matching" else "greedy",
            **(dict(positioning=True) if spec.idle.kind == "positioning" else {}),
            **(dict(delay=True) if spec.assign.delay else {}),
        )
    )
    for name, spec in SOLVERS.items()
    if spec.profiles == STREAM_PROFILES and name != "sipp_stream_dispatch"
}


@dataclass(frozen=True)
class WepaSolverSpec:
    """A separate physical model; never silently convert it into fixed-pickup tasks."""

    method: str = "gate"
    objective_family: str = "linear-physical-v2-20261024"


WEPA_SOLVERS = {
    name: WepaSolverSpec(name)
    for name in (
        "gate",
        "hungarian",
        "hga",
        "gate_anchor",
        "gate_anchor_tail",
        "gate_tail",
        "gate_trigger",
        "eta",
        "fcfs",
    )
}


def scenario_profile(scenario) -> Profile:
    if scenario.is_v9_1:
        return Profile.V91
    if scenario.is_v9:
        return Profile.V9
    return Profile.V4 if scenario.is_v4 else Profile.LEGACY


def build_controller(
    spec, initial=None, *, world_factory, action=None, ranker=None, collect=None, budget=None
):
    """Wire concrete stages at the composition root, without running a tick."""
    from agv.learning.ranker import CandidateRanker
    from agv.planning.joint import JointPlanner
    from agv.policy.bcrd import fallback
    from agv.policy.candidates import legalize
    from agv.policy.controller import (
        BaselineReporter,
        CallableAssignment,
        Controller,
        DispatchReporter,
        EtaAssignment,
        JointRepair,
        OptimizedReporter,
        PositioningIdle,
        RolloutAssignment,
        StreamReporter,
    )
    from agv.policy.greedy import greedy_action
    from agv.policy.optimized import matching_action
    from agv.policy.positioning import PositioningPolicy
    from agv.policy.stream import ArrivalMatching

    assignment = spec.assign
    if spec.result_style == "baseline":
        return Controller(
            CallableAssignment(action if action is not None else greedy_action),
            BaselineReporter(),
            capture_errors=True,
        )
    if spec.result_style == "optimized":
        repair = spec.repair or RepairSpec(enabled=False)
        if repair.learned and ranker is None:
            ranker = CandidateRanker.load(
                Path(__file__).resolve().parent / "models/candidate-ranker.json"
            )
        planner = JointPlanner(
            repair.attempts,
            router_kind=spec.router,
            neighborhoods=repair.neighborhoods,
            ranker=ranker,
            trial_budget=repair.trial_budget,
            collect=collect,
        )
        return Controller(
            CallableAssignment(matching_action if assignment.kind == "matching" else greedy_action),
            OptimizedReporter(
                assignment.kind,
                repair.enabled,
                repair.interval,
                repair.attempts,
                spec.router,
                repair.neighborhoods,
                repair.trial_budget,
                ranker,
                planner,
            ),
            repair=JointRepair(planner, repair.interval, repair.enabled),
        )
    if spec.result_style == "stream":
        from agv.planning.cache import EtaCache

        matcher = (
            ArrivalMatching(
                initial,
                delay=assignment.delay,
                eta_cache=(
                    EtaCache(assignment.eta_cache_capacity)
                    if assignment.eta_cache_capacity
                    else None
                ),
            )
            if assignment.kind == "eta_matching"
            else None
        )
        locator = (
            PositioningPolicy(
                initial,
                stat_window=spec.idle.stat_window,
                rebalance_period=spec.idle.rebalance_period,
                hotspot_zones=spec.idle.hotspot_zones,
                protect_utilization=spec.idle.protect_utilization,
            )
            if spec.idle.kind == "positioning"
            else None
        )
        return Controller(
            EtaAssignment(matcher) if matcher else CallableAssignment(fallback),
            StreamReporter(matcher, locator, locator is not None, assignment.delay),
            idle=PositioningIdle(locator) if locator else None,
        )
    if assignment.kind == "bcrd":
        configured_budget = {
            name: value
            for name, value in (
                ("max_route_calls", assignment.route_budget),
                ("max_expanded", assignment.expansion_budget),
                ("max_steps", assignment.step_budget),
            )
            if value is not None
        }
        effective_budget = {**configured_budget, **(budget or {})} if configured_budget else budget
        assign_stage = RolloutAssignment(
            dict(
                max_batches=assignment.max_batches,
                depth=assignment.depth,
                mode=assignment.mode,
                budget=effective_budget,
                min_queue_ratio=assignment.min_queue_ratio,
                event_driven=assignment.event_driven,
                tail_guard=assignment.tail_guard,
            ),
            world_factory=world_factory,
        )
        if configured_budget:
            configured_budget = effective_budget
    elif assignment.kind == "greedy":
        configured_budget = None
        assign_stage = CallableAssignment(fallback)
    else:
        configured_budget = None
        assign_stage = CallableAssignment(
            lambda observation: (
                legalize(matching_action(observation), observation) if fallback(observation) else []
            )
        )
    return Controller(
        assign_stage,
        DispatchReporter(
            assignment.kind,
            assignment.max_batches,
            assignment.depth,
            assignment.mode,
            assignment.min_queue_ratio,
            assignment.event_driven,
            spec.idle.hold_steps,
            assignment.tail_guard,
            configured_budget,
        ),
        track_observed_tasks=True,
    )


def validate_solver_profile(spec, scenario):
    """Reject unsupported profiles before constructing or mutating a world."""
    if scenario_profile(scenario) not in spec.profiles:
        if scenario.is_v9_1:
            raise ValueError(
                "V9.1 requires an explicitly registered stream solver; historical algorithms retain their original profiles"
            )
        if spec.profiles == STREAM_PROFILES:
            raise ValueError("Stream dispatch requires the explicit V9.1 profile")
        raise ValueError("Bounded standby requires the explicit V9 catalog profile")


def run_raw(name, scenario):
    if name not in SOLVERS:
        raise ValueError(f"Unknown algorithm {name!r}; choose from {', '.join(SOLVERS)}")
    spec = SOLVERS[name]
    validate_solver_profile(spec, scenario)
    from agv.runner import run

    return run(spec, scenario)


def run_named(name, scenario):
    result = run_raw(name, scenario)
    if scenario.uses_layer_rules:
        from agv.evaluation.objective import score_result

        result = score_result(scenario, result)
    return result
