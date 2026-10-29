"""Small synthetic warehouses for joint, conflict-aware optimal references.

These are explicitly reduced geometries, not real-data main experiments.
Storage has three levels with the same 2*level service rule and fixed WMS.
"""

from agv.warehouse.scenarios import Scenario


def make(name="cross_out"):
    free = {(x, y) for x in range(1, 8) for y in (2, 4)}
    free |= {(4, y) for y in range(7)} | {(x, 3) for x in (1, 7)} | {(0, 2), (0, 4)}
    homes = [(0, 2), (0, 4)]
    stations = [(4, 0), (4, 6)]
    specs = [((2, 1), (2, 2), 10), ((6, 5), (6, 4), 20), ((6, 1), (6, 2), 30)]
    pickup = {point for _, point, _ in specs}
    rows = []
    slots = []
    for bay, (shelf, point, sku) in enumerate(specs):
        rows.append(
            dict(
                position=shelf,
                loading_points=[point],
                levels=3,
                bay_id=bay,
                pair_id=bay,
                bay=1,
                face="selected-face",
            )
        )
        for level in range(1, 4):
            slots.append(
                dict(id=len(slots), sku=sku, bay=bay, shelf=shelf, level=level, points=[point])
            )
    scene = Scenario(
        width=9,
        height=7,
        blocked={(x, y) for x in range(9) for y in range(7)} - free,
        shelves={s for s, _, _ in specs},
        homes=homes,
        tasks=[],
        horizon=None,
        pickup_zones=pickup,
        transit_only=free - pickup - set(stations) - set(homes),
        stations=stations,
        map_info=dict(
            rack_catalog=rows,
            station_access="delivery_only",
            model_version="micro-joint-reference-v1",
            reference_geometry="micro joint crossing, three-level bays",
        ),
    )
    # This declared reduced graph is not a production geometry profile. Do not
    # disable/change the production profile validator to make it accept a toy.
    assert scene.shelves <= scene.blocked and set(homes) <= free
    assert not (set(homes) & (pickup | set(stations)))
    assert pickup <= free and set(stations) <= free
    reached = {homes[0]}
    queue = [homes[0]]
    for p in queue:
        for q in scene.neighbors(p):
            if q not in reached:
                reached.add(q)
                queue.append(q)
    assert reached == free
    assert all(abs(s[0] - p[0]) + abs(s[1] - p[1]) == 1 for s, p, _ in specs)
    descriptions = {
        "cross_out": [("retrieval", 10), ("retrieval", 20)],
        "mixed": [("retrieval", 10), ("delivery", 30)],
        "layers": [("retrieval", 10), ("retrieval", 10), ("retrieval", 20)],
        "mixed_burst": [("retrieval", 10), ("retrieval", 20), ("delivery", 30)],
    }
    tasks = [
        dict(id=i, kind=kind, sku=sku, release=0, port=stations[0 if kind == "delivery" else 1])
        for i, (kind, sku) in enumerate(descriptions[name])
    ]
    used = {j["sku"] for j in tasks if j["kind"] == "retrieval"}
    occupied = {s["id"] for s in slots if s["sku"] in used}
    return dict(
        case="micro-" + name,
        scene=scene,
        slots=slots,
        occupied=occupied,
        tasks=tasks,
        vehicles=2,
        close_at=0,
        size="micro-reference",
        layers=3,
    )


NAMES = ("cross_out", "mixed", "layers", "mixed_burst")


def new_world(model):
    """Construct the physical kernel through its injected routing interface."""
    from agv.planning.sipp import SafeIntervalRouter
    from agv.world.wepa import World

    return World(model, router=SafeIntervalRouter(model["scene"]))
