"""Compose the world kernel with planning, audit and idle policy services.

The kernel remains dependency-injected. This class also preserves the old
public advance() convenience API; the unified runner uses explicit idle
preparation followed by the policy-free tick().
"""

from agv.evaluation.execution import build_result
from agv.evaluation.validation import validate
from agv.planning import create_router
from agv.planning.joint import score
from agv.planning.pickup import plan_task
from agv.world.services import KernelServices
from agv.world.state import WorldState


class Environment(WorldState):
    def __init__(self, scenario, router_kind="astar", **options):
        super().__init__(
            scenario,
            router_kind,
            services=KernelServices(create_router, plan_task, validate, score, build_result),
            **options,
        )

    def reset(self, scenario=None):
        observation = super().reset(scenario)
        # Reset may replace the warehouse geometry. A cached idle decision map
        # must never survive into the next simulation, even on the same object.
        self.__dict__.pop("_standby_geometry", None)
        return observation

    def prepare_idle(self):
        if not self.idle_hold_steps and not self.ruleset.stream:
            return
        from agv.policy.idle import advance_standby
        from agv.warehouse.scenarios import Scenario

        if not hasattr(self, "_standby_geometry"):
            self._standby_geometry = Scenario.from_observation_map(
                self._public_map, self._scenario.horizon
            )
        advance_standby(self, self._standby_geometry)

    def advance(self, steps=1, *, observe=True):
        # Historical public API schedules idle actions on each step. New runners
        # issue them explicitly before tick(), which contains no policy.
        if (
            type(steps) is not int
            or steps < 1
            or (self._scenario.horizon is not None and self.time + steps > self._scenario.horizon)
        ):
            raise ValueError("Invalid advance or horizon exceeded")
        for _ in range(steps):
            self.prepare_idle()
            self.tick(observe=False)
        return self.observe() if observe else None
