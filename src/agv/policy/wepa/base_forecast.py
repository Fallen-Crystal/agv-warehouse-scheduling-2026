"""Deprecated import path; implementation lives in policy.wepa.legacy.forecast."""

import warnings

from agv.policy.wepa.legacy.forecast import rollout, snapshot

warnings.warn(
    "agv.policy.wepa.base_forecast is deprecated; historical reproductions should import "
    "agv.policy.wepa.legacy.forecast explicitly.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["snapshot", "rollout"]
