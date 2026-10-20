"""Small immutable values shared by every layer of the simulator.

This module deliberately knows nothing about scene generation, validation,
planning, policies, or the simulation kernel.
"""

from dataclasses import dataclass
from enum import Enum

Cell = tuple[int, int]
Point = Cell
VehicleId = int
Time = int


class Profile(str, Enum):
    LEGACY = "legacy"
    V4 = "math-v4-integrated"
    V9 = "mixed-v9"
    V91 = "mixed-v9.1"


@dataclass(frozen=True)
class Task:
    id: int
    pickup: Point | None
    delivery: Point
    release: int = 0
    pickup_service: int = 1
    delivery_service: int = 1
    shelf: Point | None = None
    shelf_level: int = 1
