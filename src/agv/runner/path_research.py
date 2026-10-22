"""Matched actual/shadow router injection without changing production defaults."""

from agv.planning.astar import Router
from agv.planning.hybrid_routes import HybridRouter
from agv.planning.sipp import SafeIntervalRouter
from agv.policy.bcrd import fallback
from agv.policy.f_portfolio import PortfolioSearch
from agv.policy.joint_orders import JointOrderPolicy
from agv.registry import SolverSpec
from agv.runner.environment import Environment
from agv.runner.run import run as execute

ROUTES = ("sipp", "astar", "aco_sipp", "pso_sipp", "aco_astar", "pso_astar")


def path_world_type(route, *, seed=0):
    if route not in ROUTES:
        raise ValueError("Unknown research router")

    class ResearchEnvironment(Environment):
        actual_diagnostics = None

        def __init__(self, scenario, **options):
            def router_factory(kind, scene):
                if route in ("sipp", "astar"):
                    router = (SafeIntervalRouter if route == "sipp" else Router)(scene)
                else:
                    method, timing = route.split("_")
                    router = HybridRouter(scene, method=method, timing=timing, seed=seed)
                if ResearchEnvironment.actual_diagnostics is None:
                    ResearchEnvironment.actual_diagnostics = getattr(router, "diagnostics", {})
                return router

            super().__init__(scenario, router_factory=router_factory, **options)

    return ResearchEnvironment


def run(scenario, *, route="sipp", orders="portfolio", optimizer_seed=0, candidate_budget=8):
    if not scenario.is_v9_1:
        raise ValueError("Path research requires V9.1")
    factory = path_world_type(route, seed=optimizer_seed)
    if orders == "portfolio":
        policy = PortfolioSearch(world_factory=factory, optimizer_seed=optimizer_seed)
    elif orders == "greedy":
        policy = None
    else:
        policy = JointOrderPolicy(
            world_factory=factory,
            mode=orders,
            optimizer_seed=optimizer_seed,
            candidate_budget=candidate_budget,
        )
    result = execute(
        SolverSpec(router="sipp"),
        scenario,
        world_factory=factory,
        action=policy.action if policy else fallback,
        on_assignment=policy.on_assignment if isinstance(policy, JointOrderPolicy) else None,
    )
    result["path_research"] = dict(
        route=route,
        orders=orders,
        optimizer_seed=optimizer_seed,
        diagnostics=dict(factory.actual_diagnostics or {}),
        decisions=policy.decisions if policy else [],
        commit_feedback=policy.commit_feedback if isinstance(policy, JointOrderPolicy) else [],
    )
    return result
