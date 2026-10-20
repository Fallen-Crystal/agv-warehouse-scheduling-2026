"""Historical entry point; policy implementation lives in agv.policy."""

from agv.policy.bcrd import DEFAULT_BUDGET, WEIGHTS, fallback
from agv.policy.bcrd import bcrd_action as _bcrd_action
from agv.simulation import Environment

__all__ = ["fallback", "bcrd_action", "DEFAULT_BUDGET", "WEIGHTS", "run"]


def bcrd_action(
    observation,
    max_batches=4,
    depth=None,
    mode="full",
    budget=None,
    diagnostics=None,
    min_queue_ratio=3.0,
    event_driven=True,
    tail_guard=False,
):
    """Preserve the standalone API while injecting real execution services."""
    return _bcrd_action(
        observation,
        max_batches=max_batches,
        depth=depth,
        mode=mode,
        budget=budget,
        diagnostics=diagnostics,
        min_queue_ratio=min_queue_ratio,
        event_driven=event_driven,
        tail_guard=tail_guard,
        world_factory=Environment,
    )


def run(
    scenario,
    policy="bcrd",
    *,
    max_batches=4,
    depth=None,
    mode="full",
    budget=None,
    min_queue_ratio=3.0,
    event_driven=True,
    idle_hold_steps=0,
    tail_guard=False,
):
    if idle_hold_steps and policy == "bcrd":
        raise ValueError("BCRD standby needs a separately validated shadow contract")
    if policy not in ("bcrd", "greedy", "matching"):
        raise ValueError("Unknown dispatch policy")
    from agv.registry import AssignSpec, IdleSpec, SolverSpec
    from agv.runner import run as execute

    return execute(
        SolverSpec(
            router="sipp",
            assign=AssignSpec(
                kind=policy,
                max_batches=max_batches,
                depth=depth,
                mode=mode,
                min_queue_ratio=min_queue_ratio,
                event_driven=event_driven,
                tail_guard=tail_guard,
            ),
            idle=IdleSpec(
                kind="standby" if idle_hold_steps else "profile", hold_steps=idle_hold_steps
            ),
            result_style="dispatch",
        ),
        scenario,
        budget=budget,
    )
