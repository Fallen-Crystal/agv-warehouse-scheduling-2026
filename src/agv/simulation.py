"""Backward-compatible import; Environment is composed in agv.runner."""

import warnings

from agv.runner.environment import Environment

warnings.warn(
    "agv.simulation is deprecated; import Environment from agv.runner.environment.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Environment"]
