"""Single source of truth for named solver configurations used by CLI and UI."""

from dataclasses import dataclass
from pathlib import Path

from agv.dispatch.greedy import run as run_baseline
from agv.dispatch.optimized import run as run_optimized
from agv.learning.ranker import CandidateRanker


@dataclass(frozen=True)
class SolverConfig:
    assignment: str = "greedy"
    joint: bool = True
    router_kind: str = "astar"
    neighborhoods: str = "legacy"
    trial_budget: int | None = None
    learned: bool = False


SOLVERS = {
    "baseline": None,
    "matching_only": SolverConfig(assignment="matching", joint=False),
    "joint_only": SolverConfig(),
    "matching_joint": SolverConfig(assignment="matching"),
    "sipp_joint": SolverConfig(router_kind="sipp"),
    "sipp_conflict": SolverConfig(router_kind="sipp", neighborhoods="conflict"),
    "sipp_budget": SolverConfig(router_kind="sipp", neighborhoods="conflict", trial_budget=6),
    "sipp_matching": SolverConfig(
        assignment="matching", router_kind="sipp", neighborhoods="conflict", trial_budget=6
    ),
    "sipp_learned": SolverConfig(
        router_kind="sipp", neighborhoods="conflict", trial_budget=6, learned=True
    ),
}


DISPATCH_SOLVERS = {
    "sipp_stream_dispatch": dict(policy="greedy"),
    "sipp_greedy_dispatch": dict(policy="greedy"),
    "sipp_matching_dispatch": dict(policy="matching"),
    "bcrd_budget": dict(policy="bcrd", max_batches=4),
    "bcrd_order": dict(policy="bcrd", max_batches=4, mode="order"),
    "sipp_standby8_dispatch": dict(policy="greedy", idle_hold_steps=8),
    "sipp_standby16_dispatch": dict(policy="greedy", idle_hold_steps=16),
    "sipp_standby32_dispatch": dict(policy="greedy", idle_hold_steps=32),
}
SOLVERS.update(
    {
        name: SolverConfig(assignment=name, joint=False, router_kind="sipp")
        for name in DISPATCH_SOLVERS
    }
)


def run_named(name, scenario):
    if name not in SOLVERS:
        raise ValueError(f"Unknown algorithm {name!r}; choose from {', '.join(SOLVERS)}")
    if scenario.is_v9_1 and name not in ("baseline", "sipp_stream_dispatch"):
        raise ValueError(
            "V9.1 currently supports baseline or sipp_stream_dispatch; historical BCRD/finite-wait experiments retain the v9 profile"
        )
    if name == "sipp_stream_dispatch" and not scenario.is_v9_1:
        raise ValueError("Stream dispatch requires the explicit V9.1 profile")
    config = SOLVERS[name]
    if name in DISPATCH_SOLVERS:
        from agv.dispatch.bcrd import run

        result = run(scenario, **DISPATCH_SOLVERS[name])
    elif config is None:
        result = run_baseline(scenario)
    else:
        result = run_optimized(
            scenario,
            assignment=config.assignment,
            joint=config.joint,
            router_kind=config.router_kind,
            neighborhoods=config.neighborhoods,
            trial_budget=config.trial_budget,
            ranker=CandidateRanker.load(
                Path(__file__).resolve().parents[1] / "models/candidate-ranker.json"
            )
            if config.learned
            else None,
        )
    if scenario.uses_layer_rules:
        from agv.evaluation.objective import score_result

        result = score_result(scenario, result)
    return result
