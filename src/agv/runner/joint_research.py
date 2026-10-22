"""Research composition over the sole physical execution loop."""

from agv.policy.joint_orders import JointOrderPolicy
from agv.registry import SolverSpec
from agv.runner.environment import Environment
from agv.runner.run import run as execute


def run(scenario, **options):
    if not scenario.is_v9_1:
        raise ValueError("Joint search requires V9.1")
    policy = JointOrderPolicy(world_factory=Environment, **options)
    result = execute(
        SolverSpec(router="sipp"),
        scenario,
        action=policy.action,
        on_assignment=policy.on_assignment,
    )
    result["joint_search"] = dict(
        options=options,
        decisions=policy.decisions,
        commit_feedback=policy.commit_feedback,
        weights=dict(time=0.5, response=0.3, distance=0.2),
    )
    return result
