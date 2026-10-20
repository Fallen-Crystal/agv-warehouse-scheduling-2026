"""Execution dependencies supplied by the application composition root."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class KernelServices:
    router: Callable
    plan_task: Callable
    validate: Callable
    suffix_score: Callable
    result_builder: Callable
