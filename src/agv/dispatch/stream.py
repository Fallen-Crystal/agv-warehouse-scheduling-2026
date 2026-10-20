"""Historical entry point; policy implementation lives in agv.policy."""

from agv.policy.stream import ArrivalMatching

__all__ = ["ArrivalMatching", "run"]


def run(scenario, policy="greedy", *, positioning=False, delay=False):
    if not scenario.is_v9_1:
        raise ValueError("Stream optimization requires the V9.1 profile")
    if policy not in ("greedy", "matching") or (delay and policy != "matching"):
        raise ValueError("Invalid stream policy")
    if type(positioning) is not bool:
        raise ValueError("Positioning requires the explicit V9.1 profile")
    from agv.registry import AssignSpec, IdleSpec, SolverSpec
    from agv.runner import run as execute

    return execute(
        SolverSpec(
            router="sipp",
            assign=AssignSpec(
                kind="eta_matching" if policy == "matching" else "greedy", delay=delay
            ),
            idle=IdleSpec(kind="positioning" if positioning else "profile"),
            result_style="stream",
        ),
        scenario,
    )
