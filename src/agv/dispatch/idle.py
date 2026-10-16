"""Standby on static transit floor, without consulting future orders.

A hold only delays an available vehicle's already safe fallback return.  The historical V9 policy spends a fixed per-assignment allowance. V9.1 instead
waits until a publisher close event and all released deliveries finish. Neither
policy reads unreleased orders or their total count.
"""

from copy import deepcopy


def _ordinary_transit(scenario, point):
    """Use public, immutable zone permissions rather than task destinations."""
    return (
        scenario.uses_layer_rules
        and scenario.service_axis == "catalog"
        and point in scenario.transit_only
        and point not in scenario.homes
        and point not in scenario.stations
        and point not in scenario.pickup_zones
        and scenario.free(point)
    )


def hold_return(env, vehicle, steps=1):
    """Atomically insert stationary steps before an uncommitted fallback return.

    Other vehicles retain their complete existing reservations, including their
    stationary final positions.  A collision, active service, or horizon
    violation rejects the hold without changing any environment state.
    """
    if (
        type(vehicle) is not int
        or not 0 <= vehicle < len(env._plans)
        or type(steps) is not int
        or steps < 1
    ):
        raise ValueError("Invalid standby vehicle or duration")
    if env._active[vehicle] is not None:
        raise ValueError("A committed task cannot be put on standby")
    if any(w["vehicle"] == vehicle and w["start"] <= env.time < w["end"] for w in env._idle_waits):
        raise ValueError("Standby already scheduled")
    scenario = env._scenario
    old_path = env._plans[vehicle]
    point = old_path[0]
    if not _ordinary_transit(scenario, point):
        raise ValueError("Standby requires ordinary catalog transit floor")
    if len(old_path) <= 1:
        raise ValueError("No fallback return to hold")
    record_index = next(
        (i for i in range(len(env._records) - 1, -1, -1) if env._records[i]["vehicle"] == vehicle),
        None,
    )
    position_event = (
        next((r for r in reversed(env._position_events) if r["vehicle"] == vehicle), None)
        if env.positioning
        else None
    )
    shadow_return = getattr(env, "_visible_old_routes", {}).get(vehicle)
    if record_index is None and position_event is None and shadow_return is None:
        raise ValueError("No accepted task has a fallback return")
    latest = env._records[record_index] if record_index is not None else shadow_return
    old_end = env.time + len(old_path) - 1
    if latest is not None and (
        latest["delivery_end"] > env.time or latest["return_end"] != old_end
    ):
        raise ValueError("Fallback return metadata does not match current suffix")
    if scenario.horizon is not None and old_end + steps > scenario.horizon:
        raise ValueError("Standby exceeds supplied horizon")

    plans = list(env._plans)
    plans[vehicle] = [point] * steps + list(old_path)
    if env.plan_reservations().conflict(plans[vehicle], env.time, vehicle):
        raise ValueError("Standby conflicts with an existing route or edge swap")

    records = list(env._records)
    if record_index is not None:
        records[record_index] = deepcopy(latest)
        records[record_index]["return_end"] = old_end + steps
        records[record_index]["return_arrival"] = old_end + steps
    waits = [dict(w) for w in env._idle_waits]
    adjacent = next(
        (w for w in reversed(waits) if w["vehicle"] == vehicle and w["end"] == env.time),
        None,
    )
    if adjacent is None:
        waits.append(dict(vehicle=vehicle, start=env.time, end=env.time + steps))
    else:
        adjacent["end"] += steps
    env._replace_plan(vehicle, plans[vehicle], held_steps=steps)
    env._records, env._idle_waits = records, waits
    if position_event is not None:
        position_event["return_end"] = old_end + steps
    if record_index is None and shadow_return is not None:
        shadow_return.update(return_end=old_end + steps, return_arrival=old_end + steps)
    return dict(vehicle=vehicle, accepted=True, start=env.time, end=env.time + steps)


def advance_standby(env):
    """Spend at most one visible-state hold per available vehicle this step.

    The environment resets a vehicle's count when accepting its next task.
    Failed holds consume no allowance and leave its safe return in place.
    """
    limit = env.idle_hold_steps
    if type(limit) is not int or limit < 0:
        raise ValueError("idle_hold_steps must be a nonnegative integer")
    stream = env._scenario.is_v9_1
    if stream:
        from agv.dispatch.order_stream import final_return_ready

        if final_return_ready(env):
            return
    if not limit and not stream:
        return
    if not env._scenario.uses_layer_rules or env._scenario.service_axis != "catalog":
        return
    for vehicle, path in enumerate(env._plans):
        if env.positioning:
            target = env._position_targets[vehicle]
            if target is None or env.time < target["arrival"] or path[0] != target["target"]:
                continue
        if (
            env._active[vehicle] is not None
            or len(path) <= 1
            or (not stream and env._idle_hold_counts[vehicle] >= limit)
            or not _ordinary_transit(env._scenario, path[0])
        ):
            continue
        try:
            hold_return(env, vehicle)
        except ValueError:
            # Preserve the original safe return when a reservation blocks a hold.
            if env.positioning:
                env._position_targets[vehicle] = None
            continue
        env._idle_hold_counts[vehicle] += 1
