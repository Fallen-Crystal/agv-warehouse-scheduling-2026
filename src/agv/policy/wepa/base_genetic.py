"""Deprecated import path; implementation lives in policy.wepa.legacy.genetic."""

import warnings

from agv.policy.wepa.legacy.genetic import candidates

warnings.warn(
    "agv.policy.wepa.base_genetic is deprecated; historical reproductions should import "
    "agv.policy.wepa.legacy.genetic explicitly.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["candidates"]
