"""Pure mixed-flow inventory, shelf-order and trip admissibility rules.

The WEPA profile is separate from the historical outbound-only Task contract.
These helpers own no execution state and do not import the simulator or router.
"""


def eligible_slot(slots, stock, out_reserved, in_reserved, job):
    """Preserve deterministic WMS allocation, independent of vehicle choice."""
    outbound = job["kind"] == "retrieval"
    opposite = in_reserved if outbound else out_reserved
    blocked_bays = {slots[sid]["bay"] for sid in opposite}
    reservations = out_reserved if outbound else in_reserved
    eligible = [
        slot
        for slot in slots
        if slot["sku"] == job["sku"]
        and (slot["id"] in stock) == outbound
        and slot["id"] not in reservations
        and slot["bay"] not in blocked_bays
    ]
    eligible.sort(key=lambda slot: (slot["bay"], -slot["level"] if outbound else slot["level"]))
    return eligible[0]["id"] if eligible else None


def dispatchable(slots, stock, in_reserved, locks, slot_id, job, time):
    slot = slots[slot_id]
    if locks.get(slot["bay"], 0) > time:
        return False
    if job["kind"] == "retrieval":
        return not any(
            q["bay"] == slot["bay"] and q["level"] > slot["level"] and q["id"] in stock
            for q in slots
        )
    return not any(
        q["bay"] == slot["bay"] and q["level"] < slot["level"] and q["id"] in in_reserved
        for q in slots
    )


def validate_trip(scene, slot, job, vehicle, time, position, path, record):
    """Reject malformed proposals before any route, lock or assignment changes."""
    if any(
        not isinstance(point, (tuple, list))
        or len(point) != 2
        or any(type(value) is not int for value in point)
        for point in path
    ):
        raise ValueError("Trip coordinates must be integer cells")
    if not path or path[0] != position or path[-1] != scene.homes[vehicle]:
        raise ValueError("Trip must start at current position and include fallback home")
    if (record.get("task"), record.get("vehicle"), record.get("slot")) != (
        job["id"],
        vehicle,
        slot["id"],
    ):
        raise ValueError("Trip task, vehicle or slot differs from WMS binding")
    keys = ("assigned_at", "pickup_arrival", "pickup_end", "drop_arrival", "end")
    times = [record.get(key) for key in keys]
    if not all(type(value) is int for value in times):
        raise ValueError("Trip event times must be integers")
    assigned, pickup_at, pickup_end, drop_at, end = times
    if not (
        job["release"]
        <= assigned
        == time
        <= pickup_at
        < pickup_end
        <= drop_at
        < end
        <= time + len(path) - 1
    ):
        raise ValueError("Invalid trip event chronology")
    pickup, drop = record.get("pickup"), record.get("drop")
    if job["kind"] == "delivery":
        endpoints = pickup == job["port"] and drop in slot["points"]
        services = pickup_end - pickup_at == 1 and end - drop_at == 2 * slot["level"]
        port_at, port_end = pickup_at, pickup_end
    else:
        endpoints = pickup in slot["points"] and drop == job["port"]
        services = pickup_end - pickup_at == 2 * slot["level"] and end - drop_at == 1
        port_at, port_end = drop_at, end
    if not endpoints or not services:
        raise ValueError("Trip changed a legal service side or service duration")
    for point, start, finish in ((pickup, pickup_at, pickup_end), (drop, drop_at, end)):
        if any(path[t - time] != point for t in range(start, finish + 1)):
            raise ValueError("Trip service must be continuous")
    foreign_homes = set(scene.homes) - {scene.homes[vehicle]}
    for index, point in enumerate(path):
        if not scene.free(point) or point in foreign_homes:
            raise ValueError("Trip enters a blocked cell or foreign home")
        # A new trip may interrupt the previous fallback exactly at its unload
        # completion; its first vertex still belongs to that preceding service.
        if (
            index
            and point in scene.stations
            and not (point == job["port"] and port_at <= time + index <= port_end)
        ):
            raise ValueError("Trip uses a terminal for transit or idle parking")
        if index and sum(abs(a - b) for a, b in zip(path[index - 1], point)) > 1:
            raise ValueError("Trip contains a non-four-neighbor move")
