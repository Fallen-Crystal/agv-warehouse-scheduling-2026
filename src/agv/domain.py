"""Backward-compatible imports for the original public data-model module.

New code should import immutable values from ``agv.core`` and scene construction
from ``agv.warehouse.scenarios``.
"""

from agv.core import Point, Task
from agv.warehouse.scenarios import Scenario, example

__all__ = ["Point", "Scenario", "Task", "example"]
