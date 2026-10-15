"""Path planners share a leg()/distance() contract and search counters."""

from agv.planning.astar import Router
from agv.planning.sipp import SafeIntervalRouter


def create_router(kind, scenario):
    if kind == "astar":
        return Router(scenario)
    if kind == "sipp":
        return SafeIntervalRouter(scenario)
    raise ValueError("router must be 'astar' or 'sipp'")
