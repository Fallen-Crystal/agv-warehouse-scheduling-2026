"""One execution loop, with assignment committed before idle/repair decisions."""

from typing import TYPE_CHECKING

from agv.policy.controller import PolicyContext
from agv.runner.environment import Environment

if TYPE_CHECKING:
    from agv.registry import SolverSpec


def run(
    spec: "SolverSpec",
    scenario,
    *,
    action=None,
    ranker=None,
    collect=None,
    budget=None,
    on_assignment=None,
    world_factory=None,
):
    # Construction is delegated to the composition root. Policies themselves do
    # not construct or inspect an Environment.
    from agv.registry import build_controller, validate_solver_profile

    validate_solver_profile(spec, scenario)
    world_factory = world_factory or Environment

    env = world_factory(
        scenario,
        router_kind=spec.router,
        idle_hold_steps=spec.idle.hold_steps,
        positioning=spec.idle.kind == "positioning",
    )
    observe = getattr(env, "observe_view", env.observe)
    # Historical stream policies initialize their geometry/history with one
    # initial observation, even when the scenario is already complete.
    initial = observe() if spec.result_style == "stream" else None
    controller = build_controller(
        spec,
        initial,
        world_factory=world_factory,
        action=action,
        ranker=ranker,
        collect=collect,
        budget=budget,
    )
    context = PolicyContext()
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        observation = observe()
        controller.observe(observation, context)
        try:
            assignments = controller.assign.decide(observation, context)
        except Exception as error:
            if not controller.capture_errors:
                raise
            env.record_execution_error("policy_error", error)
            break
        try:
            feedback = env.assign(assignments)
        except ValueError as error:
            if not controller.capture_errors:
                raise
            env.record_execution_error("invalid_action", error)
            break
        if on_assignment is not None:
            on_assignment(observation, feedback, observe())
        # Never reuse the pre-assignment observation: available vehicles and
        # reservations may both have changed after the assignment commit.
        if controller.idle and controller.idle.due(observation):
            for vehicle, target in controller.idle.decide(observe(), context):
                context.position_attempts += 1
                try:
                    env.reposition(vehicle, target)
                except ValueError:
                    context.position_rejections += 1
        if controller.repair and controller.repair.due(env.time, feedback):
            proposal = controller.repair.decide(observe(), context)
            if proposal:
                env.apply_replan(proposal)
        if env.stop_if_stalled(feedback):
            break
        env.prepare_idle()
        env.tick(1, observe=False)
    return controller.reporter.finish(env.result(), context)
