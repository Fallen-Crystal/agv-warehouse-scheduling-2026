"""Historical preview API; concrete execution is wired at this boundary.

New policy code receives its world factory from the composition root. This
adapter preserves standalone ``ShadowState.from_observation`` callers.
"""

from agv.policy.forecast import ShadowState as VisiblePreview
from agv.policy.forecast import _safe_greedy, _task
from agv.simulation import Environment


class ShadowState(VisiblePreview):
    def __init__(self, observation, router_kind, event_driven=True, *, world_factory=Environment):
        super().__init__(observation, router_kind, event_driven, world_factory=world_factory)

    @classmethod
    def from_observation(cls, observation, router_kind="sipp", event_driven=True):
        return super().from_observation(
            observation, router_kind, event_driven, world_factory=Environment
        )


__all__ = ["ShadowState", "_safe_greedy", "_task"]
