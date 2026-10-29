"""Deprecated compatibility package; current strategies live in agv.policy."""

import warnings

warnings.warn(
    "agv.dispatch is deprecated; import strategies from agv.policy and solvers from agv.registry.",
    DeprecationWarning,
    stacklevel=2,
)
