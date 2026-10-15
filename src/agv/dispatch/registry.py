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
    "sipp_learned": SolverConfig(
        router_kind="sipp", neighborhoods="conflict", trial_budget=6, learned=True
    ),
}


def run_named(name, scenario):
    if name not in SOLVERS:
        raise ValueError(f"Unknown algorithm {name!r}; choose from {', '.join(SOLVERS)}")
    config = SOLVERS[name]
    if config is None:
        return run_baseline(scenario)
    return run_optimized(
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
