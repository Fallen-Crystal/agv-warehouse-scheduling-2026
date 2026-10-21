"""Explicit optional research runner; registered defaults remain untouched."""

from agv.policy.bcrd import fallback
from agv.policy.research_search import ReservationPriority, SearchPolicy
from agv.registry import SolverSpec
from agv.runner.environment import Environment
from agv.runner.run import run as run_composed

ORDER_MODE = "ga"
COORDINATE = False


def run(scenario, *, mode=None, coordinate=None):
    if not scenario.is_v9_1:
        raise ValueError("Research runner requires V9.1")
    mode = ORDER_MODE if mode is None else mode
    coordinate = COORDINATE if coordinate is None else coordinate
    if mode not in ("greedy", "ga", "exact"):
        raise ValueError("Unknown research mode")
    policy = SearchPolicy(world_factory=Environment, mode=mode) if mode != "greedy" else None
    coordinator = ReservationPriority(world_factory=Environment) if coordinate else None

    def action(obs):
        pairs = policy.action(obs) if policy else fallback(obs)
        return coordinator.action(obs, pairs) if coordinator else pairs

    r = run_composed(SolverSpec(router="sipp"), scenario, action=action)
    r["research"] = dict(
        mode=mode,
        coordinate=coordinate,
        coordination=coordinator.decisions if coordinator else [],
        decisions=policy.decisions if policy else [],
    )
    return r
