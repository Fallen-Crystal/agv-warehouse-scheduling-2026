"""Historical entry point; policy implementation lives in agv.policy."""

from agv.policy.greedy import greedy_action

__all__ = ["greedy_action", "run"]

from agv.runner.compat import run_baseline as run
