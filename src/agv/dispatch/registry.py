"""Compatibility imports; solver specifications live in :mod:`agv.registry`."""

from agv.registry import (
    ALL_PROFILES,
    DISPATCH_SOLVERS,
    HISTORICAL_PROFILES,
    SOLVERS,
    STREAM_PROFILES,
    STREAM_SOLVERS,
    AssignSpec,
    IdleSpec,
    RepairSpec,
    SolverSpec,
    run_named,
    run_raw,
)

__all__ = [
    "ALL_PROFILES",
    "DISPATCH_SOLVERS",
    "HISTORICAL_PROFILES",
    "SOLVERS",
    "STREAM_PROFILES",
    "STREAM_SOLVERS",
    "AssignSpec",
    "IdleSpec",
    "RepairSpec",
    "SolverSpec",
    "run_named",
    "run_raw",
]
