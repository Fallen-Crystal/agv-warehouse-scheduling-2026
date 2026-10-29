"""Backward-compatible imports for the original public data-model module.

New code should import immutable values from ``agv.core`` and scene construction
from ``agv.warehouse.scenarios``.
"""

import warnings

from agv.core import Point, Task
from agv.warehouse.scenarios import Scenario, example

warnings.warn(
    "agv.domain is deprecated; import Task from agv.core and Scenario/example from agv.warehouse.scenarios.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Point", "Scenario", "Task", "example"]
