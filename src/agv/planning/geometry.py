"""Thread-local cache for immutable observation geometry and A* routers.

Every dispatch step rebuilds the same static map, validates it and throws away
the router distance caches.  The map is immutable for the duration of a run, so
a bounded thread-local cache can reuse the validated Scenario and, for the
stateless A* reference router, its distance cache.  SIPP routers are not cached
because their statistics are mutable and reported per planner.
"""

import json
import threading

from agv.domain import Scenario
from agv.planning import create_router

_LOCAL = threading.local()
_LIMIT = 8


def _map_key(observation):
    return (
        json.dumps(observation["map"], sort_keys=True, separators=(",", ":")),
        observation["horizon"],
    )


def scenario_from_observation(observation):
    """Return the cached validated static Scenario for this observation."""
    key = _map_key(observation)
    cache = getattr(_LOCAL, "scenarios", None)
    if cache is None:
        cache = _LOCAL.scenarios = {}
    if key in cache:
        return cache[key]
    scenario = Scenario.from_observation_map(observation["map"], observation["horizon"])
    if len(cache) >= _LIMIT:
        cache.pop(next(iter(cache)))
    cache[key] = scenario
    return scenario


def from_observation(observation, router_kind="astar"):
    """Return a cached ``(Scenario, router)``; only A* routers are cached."""
    scenario = scenario_from_observation(observation)
    if router_kind != "astar":
        return scenario, create_router(router_kind, scenario)
    key = _map_key(observation)
    cache = getattr(_LOCAL, "routers", None)
    if cache is None:
        cache = _LOCAL.routers = {}
    if key in cache:
        return scenario, cache[key]
    router = create_router("astar", scenario)
    if len(cache) >= _LIMIT:
        cache.pop(next(iter(cache)))
    cache[key] = router
    return scenario, router
