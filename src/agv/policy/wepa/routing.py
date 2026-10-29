"""Use the one mainline router implementation, preserving forecast counters."""

from agv.planning.astar import Router
from agv.planning.sipp import SafeIntervalRouter


def make_router(scene, kind="sipp", seed=0, cache=None, stats=None):
    if kind == "sipp":
        router = SafeIntervalRouter(scene)
    elif kind == "astar":
        router = Router(scene)
    else:
        raise ValueError("Unsupported integrated WEPA routing backend")
    if cache is not None:
        router.cache = cache
    if stats is not None:
        router.stats = dict(stats)
    return router
