"""Optional fixed-F experiment runner over the existing execution kernel."""

from agv.policy.f_portfolio import PortfolioSearch
from agv.policy.f_search import ObjectiveSearch
from agv.registry import SolverSpec
from agv.runner.environment import Environment
from agv.runner.run import run as execute


def run(scenario, **options):
    if not scenario.is_v9_1:
        raise ValueError("Fixed-F experiment requires V9.1")
    if options.get("method") == "portfolio":
        policy = PortfolioSearch(
            world_factory=Environment, optimizer_seed=options.get("optimizer_seed", 0)
        )
    else:
        policy = ObjectiveSearch(world_factory=Environment, **options)
    r = execute(SolverSpec(router="sipp"), scenario, action=policy.action)
    r["f_search"] = dict(
        options=options,
        decisions=policy.decisions,
        acceptance_weights=dict(time=0.5, response=0.3, distance=0.2),
    )
    return r
