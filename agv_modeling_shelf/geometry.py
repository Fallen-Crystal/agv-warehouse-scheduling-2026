"""Share the immutable map geometry between policies and the joint planner.

Every call to ``greedy_action`` or ``matching_action`` used to rebuild the same
``Scenario`` and ``Router`` (and therefore the same BFS caches) from the
observation map.  The map is immutable during a run, so one cached pair can be
reused by every policy call for that geometry.  This is decision-preserving:
the cached objects contain no per-step state.
"""
from model import Scenario
from routing import Router

_CACHE = {}


def from_observation(observation):
    """Return ``(scenario, router)`` for the observation's static map."""
    m = observation['map']
    key = (m['width'], m['height'], tuple(map(tuple, m['blocked'])),
           tuple(map(tuple, m['shelves'])), tuple(map(tuple, m['homes'])),
           observation['horizon'])
    cached = _CACHE.get(key)
    if cached is None:
        scenario = Scenario(m['width'], m['height'], set(map(tuple, m['blocked'])),
                            set(map(tuple, m['shelves'])), list(map(tuple, m['homes'])),
                            [], observation['horizon'])
        cached = (scenario, Router(scenario))
        _CACHE[key] = cached
    return cached
