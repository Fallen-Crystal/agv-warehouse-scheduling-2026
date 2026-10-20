"""Historical entry point; policy implementation lives in agv.policy."""

from agv.policy.optimized import matching_action

__all__ = ["matching_action", "run"]

from agv.runner.compat import run_optimized as run
