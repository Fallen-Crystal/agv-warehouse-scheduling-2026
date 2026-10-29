"""Deprecated import path; implementation lives in policy.wepa.legacy.proxy."""

import warnings

from agv.policy.wepa.legacy.proxy import MixedCosts

warnings.warn(
    "agv.policy.wepa.legacy_proxy is deprecated; historical reproductions should import "
    "agv.policy.wepa.legacy.proxy explicitly.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["MixedCosts"]
