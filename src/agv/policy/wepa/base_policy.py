"""Deprecated import path; implementation lives in policy.wepa.legacy.policy."""

import warnings

from agv.policy.wepa.legacy.policy import LinearPolicy

warnings.warn(
    "agv.policy.wepa.base_policy is deprecated; historical reproductions should import "
    "agv.policy.wepa.legacy.policy explicitly.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["LinearPolicy"]
