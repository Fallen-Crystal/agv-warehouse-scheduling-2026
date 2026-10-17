"""Atomic, interruptible V9.1 empty movements with a complete home fallback."""

from copy import deepcopy

from agv.dispatch.idle import _ordinary_transit
from agv.dispatch.order_stream import final_return_ready
from agv.planning.reservations import reservations


def reposition(env, vehicle, target):
    if not env.positioning or not env._scenario.is_v9_1:
        raise ValueError("Repositioning is an explicit V9.1 opt-in")
    if type(vehicle) is not int or not 0 <= vehicle < len(env._plans):
        raise ValueError("Unknown vehicle")
    if env._active[vehicle] is not None:
        raise ValueError("A committed task cannot be repositioned")
    if (
        not isinstance(target, (tuple, list))
        or len(target) != 2
        or any(type(x) is not int for x in target)
    ):
        raise ValueError("Target must contain two integer coordinates")
    target = tuple(target)
    scenario, now = env._scenario, env.time
    home = scenario.homes[vehicle]
    if target == home and env._plans[vehicle][0] == home:
        raise ValueError("Vehicle is already at home")
    if target != home and not _ordinary_transit(scenario, target):
        raise ValueError("Positioning target must be ordinary transit floor or own home")
    if final_return_ready(env) and target != home:
        raise ValueError("Final return cannot be replaced by positioning")
    peers = [path for k, path in enumerate(env._plans) if k != vehicle]
    vertices, edges = reservations(peers, now)
    outward = env._router.leg(env._plans[vehicle][0], target, now, vehicle, vertices, edges)
    if outward is None:
        raise ValueError("No safe positioning route")
    arrival = now + len(outward) - 1
    back = env._router.leg(target, home, arrival, vehicle, vertices, edges)
    if back is None:
        raise ValueError("No safe fallback return")
    path = outward + back[1:]
    if env.plan_reservations().conflict(path, now, vehicle):
        raise ValueError("Positioning conflicts with an existing reservation")
    end = now + len(path) - 1
    records = list(env._records)
    index = next(
        (i for i in range(len(records) - 1, -1, -1) if records[i]["vehicle"] == vehicle), None
    )
    if index is not None:
        records[index] = deepcopy(records[index])
        records[index].update(return_end=end, return_arrival=end)
    waits = [
        {**w, "end": min(w["end"], now)} if w["vehicle"] == vehicle else w for w in env._idle_waits
    ]
    event = dict(vehicle=vehicle, start=now, target=target, arrival=arrival, return_end=end)
    env._records = records
    env._idle_waits = [w for w in waits if w["start"] < w["end"]]
    env._replace_plan(vehicle, path)
    env._position_targets[vehicle] = (
        None if target == home else dict(target=target, arrival=arrival)
    )
    env._position_events = [
        e for e in env._position_events if not (e["vehicle"] == vehicle and e["start"] == now)
    ]
    env._position_events.append(event)
    return deepcopy(event)
