"""Historical callable signatures, compiled into typed solver specifications.

Application and experiment code uses these adapters when options are supplied
programmatically rather than through a registered public solver name. All
execution still goes through the single runner.
"""

from agv.policy.greedy import greedy_action
from agv.registry import AssignSpec, IdleSpec, RepairSpec, SolverSpec
from agv.runner.run import run as execute


def run_baseline(scenario, policy=greedy_action):
    return execute(SolverSpec(), scenario, action=lambda observation: policy(observation))


def run_optimized(
    scenario,
    assignment="matching",
    joint=True,
    interval=5,
    attempts=8,
    router_kind="astar",
    neighborhoods="legacy",
    ranker=None,
    trial_budget=None,
    collect=None,
):
    if assignment not in ("matching", "greedy") or type(interval) is not int or interval < 1:
        raise ValueError("Invalid optimizer options")
    if type(joint) is not bool:
        raise ValueError("joint must be a boolean")
    return execute(
        SolverSpec(
            router=router_kind,
            assign=AssignSpec(kind=assignment),
            repair=RepairSpec(
                enabled=joint,
                interval=interval,
                attempts=attempts,
                neighborhoods=neighborhoods,
                trial_budget=trial_budget,
            ),
            result_style="optimized",
        ),
        scenario,
        ranker=ranker,
        collect=collect,
    )


def run_dispatch(
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
