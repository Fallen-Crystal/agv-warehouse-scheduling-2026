"""V4 modelling assumptions, kept separate from route-search decisions.

Adapted from the teammate's integrated V4 model. Layer order, service times
and objective weights are project assumptions, not physical measurements.
"""

from collections import deque

MODEL_VERSION = "math-v4-integrated"
_FLAGS = {
    "model_version": MODEL_VERSION,
    "service_rule": "2l",
    "kind": "structured-v1",
    "rules_version": "delivery-only-v1",
    "station_access": "delivery_only",
    "geometry_layout": "paired_rows",
    "layer_order": "descending_per_face",
    "loading_rule": "independent_sides",
}
_INFO_FIELDS = set(_FLAGS) | {
    "objective_weights",
    "size",
    "rows",
    "columns",
    "shelf_length",
    "shelf_thickness",
    "base_aisle_width",
    "base_work_width",
    "aisle_width",
    "work_width",
    "scale_increment",
    "rack_catalog",
    "layer_count",
    "side_capacity",
    "perimeter_left",
    "perimeter_right",
    "perimeter_top",
    "perimeter_bottom",
    "removed_empty_rows",
    "obstacle_layout",
    "layout_variant",
    "obstacles",
    "facility_bands",
    "facility_reserved_width",
    "aisle_width_includes_columns",
    "aisle_clear_at_columns",
    "equipment_side",
    "equipment_strip_width",
    "equipment_strip_x",
    "equipment_footprint",
    "perimeter_clear_at_equipment",
    "column_count",
    "equipment_count",
    "obstacle_cells",
}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _point(value):
    return (
        isinstance(value, (tuple, list)) and len(value) == 2 and all(type(v) is int for v in value)
    )


def validate_profile(scenario):
    """Reject unknown/mixed profiles and validate V4 geometry metadata.

    The legacy profile has no auxiliary zone/station metadata. In particular,
    stripping a V4 version flag must fail instead of silently changing rules.
    """
    s = scenario
    _require(isinstance(s.map_info, dict), "map_info must be an object")
    _require(type(s.service_axis) is str, "Invalid service axis")
    _require(isinstance(s.pickup_zones, set), "pickup_zones must be a set")
    _require(isinstance(s.transit_only, set), "transit_only must be a set")
    _require(isinstance(s.stations, list), "stations must be a list")
    if s.is_v9:
        from agv.warehouse.mixed import validate_profile as validate_mixed

        validate_mixed(s)
        return
    if not s.is_v4:
        _require(
            s.service_axis == "any"
            and not s.map_info
            and not s.pickup_zones
            and not s.transit_only
            and not s.stations,
            "Unknown or mixed scene profile; extended rules require explicit V4 metadata",
        )
        return
    info = s.map_info
    _require(not set(info) - _INFO_FIELDS, "Unknown V4 metadata fields")
    _require(all(info.get(k) == v for k, v in _FLAGS.items()), "Missing or unsupported V4 rules")
    _require(s.service_axis == "north_south", "V4 requires north_south shelf service")
    _require(
        type(info.get("layer_count")) is int and 1 <= info["layer_count"] <= 5,
        "Invalid V4 layer count",
    )
    _require(
        type(info.get("side_capacity")) is int and info["side_capacity"] == 1,
        "V4 side capacity must be one",
    )
    weights = info.get("objective_weights")
    _require(
        isinstance(weights, list)
        and len(weights) == 3
        and all(type(v) in (int, float) for v in weights)
        and weights == [0.5, 0.3, 0.2],
        "Unsupported V4 objective weights",
    )
    _require(
        bool(s.shelves) and bool(s.homes) and 1 <= len(s.homes) <= 10,
        "V4 needs shelves and 1 to 10 vehicles",
    )
    for p in s.pickup_zones | s.transit_only | set(s.stations):
        _require(_point(p) and s.free(p), "Invalid V4 zone or station")
    _require(
        len(set(s.stations)) == len(s.stations) and bool(s.stations),
        "V4 needs distinct delivery stations",
    )
    _require(
        not set(s.homes) & (s.pickup_zones | set(s.stations)), "Home overlaps a V4 service zone"
    )
    _require(not set(s.stations) & s.pickup_zones, "Station overlaps loading zone")
    free = {(x, y) for x in range(s.width) for y in range(s.height)} - s.blocked
    expected = {
        (x, y + dy)
        for x, y in s.shelves
        for dy in (-1, 1)
        if s.free((x, y + dy)) and (x, y + dy) not in s.homes and (x, y + dy) not in s.stations
    }
    _require(s.pickup_zones == expected, "Loading zones must match legal long-side neighbors")
    _require(
        s.transit_only == free - expected - set(s.homes) - set(s.stations),
        "Incorrect transit zone classification",
    )
    seen, queue = {s.homes[0]}, deque([s.homes[0]])
    while queue:
        for p in s.neighbors(queue.popleft()):
            if p not in seen:
                seen.add(p)
                queue.append(p)
    _require(seen == free, "V4 map has disconnected free areas")

    catalog = info.get("rack_catalog")
    _require(
        isinstance(catalog, list) and len(catalog) == len(s.shelves), "Rack catalog size mismatch"
    )
    entries = {"position", "pair_id", "face", "group_id", "bay", "bay_id", "levels"}
    pairs, positions, identifiers = {}, set(), set()
    for row in catalog:
        _require(isinstance(row, dict) and set(row) == entries, "Invalid rack catalog fields")
        _require(_point(row["position"]), "Invalid rack catalog coordinates")
        pos = tuple(row["position"])
        _require(pos in s.shelves and pos not in positions, "Duplicate or unknown rack position")
        positions.add(pos)
        _require(
            type(row["bay"]) is int
            and row["bay"] >= 1
            and type(row["levels"]) is int
            and row["levels"] == info["layer_count"],
            "Invalid rack bay or layer count",
        )
        _require(
            type(row["group_id"]) is str
            and row["group_id"].startswith("R")
            and type(row["pair_id"]) is str
            and row["pair_id"].startswith("P")
            and type(row["face"]) is str
            and row["face"] in ("U", "D"),
            "Invalid paired shelf identifier",
        )
        expected_id = row["group_id"] + f"-B{row['bay']:02d}"
        _require(
            row["bay_id"] == expected_id and expected_id not in identifiers,
            "Invalid or duplicate rack bay ID",
        )
        identifiers.add(expected_id)
        faces = pairs.setdefault((row["pair_id"], row["bay"]), {})
        _require(row["face"] not in faces, "Duplicate paired shelf face")
        faces[row["face"]] = pos
        candidates = [p for p in s.neighbors(pos) if p[0] == pos[0] and p in s.pickup_zones]
        _require(len(candidates) == 1, "V4 shelf must have exactly one outer loading side")
    for faces in pairs.values():
        _require(set(faces) == {"U", "D"}, "Missing paired shelf face")
        _require(
            faces["D"] == (faces["U"][0], faces["U"][1] + 1),
            "Paired shelves must touch back to back",
        )

    objects = info.get("obstacles")
    _require(isinstance(objects, list), "V4 obstacles must be a list")
    cells = set()
    for obj in objects:
        _require(
            isinstance(obj, dict)
            and set(obj) == {"kind", "cells"}
            and type(obj["kind"]) is str
            and obj["kind"] in ("column", "equipment")
            and isinstance(obj["cells"], list)
            and bool(obj["cells"]),
            "Invalid structural obstacle",
        )
        for p in obj["cells"]:
            _require(_point(p), "Invalid obstacle cell")
            p = tuple(p)
            _require(p in s.blocked and p not in cells, "Duplicate or unblocked obstacle cell")
            cells.add(p)
    boundary = {(x, 0) for x in range(s.width)}
    _require(s.blocked - s.shelves - boundary == cells, "Unregistered wall or obstacle")
    _require(
        not cells & (s.pickup_zones | set(s.homes) | set(s.stations)),
        "Obstacle occupies service zone",
    )

    # Optional descriptive fields remain strictly typed; no arbitrary metadata
    # can carry hidden generator state, future tasks, or reference denominators.
    string_fields = {"size", "obstacle_layout", "equipment_side"}
    complex_fields = {
        "rack_catalog",
        "obstacles",
        "facility_bands",
        "equipment_footprint",
        "objective_weights",
    }
    for name in set(info) - set(_FLAGS) - complex_fields:
        value = info[name]
        if name in string_fields:
            _require(type(value) is str, f"Invalid V4 metadata {name}")
        elif name == "aisle_width_includes_columns":
            _require(type(value) is bool and value, "Aisle width must include columns")
        else:
            _require(type(value) is int and value >= 0, f"Invalid V4 metadata {name}")
    if "aisle_width" in info:
        _require(info["aisle_width"] == 2, "V4 connecting aisle width must be two")
    if "work_width" in info:
        _require(info["work_width"] in (2, 3, 4), "Invalid V4 work aisle width")
    bands = info.get("facility_bands", [])
    band_keys = {"connector", "x", "width", "traffic_x", "traffic_width"}
    _require(isinstance(bands, list), "Invalid facility bands")
    for band in bands:
        _require(
            isinstance(band, dict)
            and set(band) == band_keys
            and all(type(v) is int and v >= 0 for v in band.values()),
            "Invalid facility band",
        )
        _require(band["width"] > 0 and band["traffic_width"] > 0, "Empty facility or traffic band")
    if "equipment_footprint" in info:
        footprint = info["equipment_footprint"]
        _require(
            isinstance(footprint, list)
            and len(footprint) == 2
            and all(type(v) is int for v in footprint)
            and footprint[0] in (1, 2)
            and footprint[1] >= 3,
            "Invalid equipment footprint",
        )
    if "size" in info:
        _require(
            info["size"] in ("small", "medium", "large", "xlarge", "xxlarge"), "Unknown V4 size"
        )
    if "obstacle_layout" in info:
        _require(
            info["obstacle_layout"] in ("none", "columns", "columns_equipment"),
            "Unknown V4 obstacle layout",
        )
    for field, actual in (
        ("column_count", sum(o["kind"] == "column" for o in objects)),
        ("equipment_count", sum(o["kind"] == "equipment" for o in objects)),
        ("obstacle_cells", len(cells)),
    ):
        if field in info:
            _require(info[field] == actual, f"Inconsistent V4 {field}")
    first, last = min(y for x, y in s.shelves), max(y for x, y in s.shelves)
    for obj in objects:
        if obj["kind"] == "column":
            if "facility_bands" in info:
                _require(
                    all(
                        any(band["x"] <= x < band["x"] + band["width"] for band in bands)
                        for x, y in obj["cells"]
                    ),
                    "Column outside its reserved strip",
                )
            if "perimeter_left" in info and "perimeter_right" in info:
                _require(
                    all(
                        info["perimeter_left"] <= x < s.width - info["perimeter_right"]
                        and first <= y <= last + 1
                        for x, y in obj["cells"]
                    ),
                    "Column occupies perimeter aisle",
                )
        else:
            _require("equipment_footprint" in info, "Missing equipment footprint")
            width, length = info["equipment_footprint"]
            object_cells = set(map(tuple, obj["cells"]))
            x0 = min(x for x, y in object_cells)
            y0 = min(y for x, y in object_cells)
            _require(x0 in (0, s.width - width), "Equipment must be anchored to a side edge")
            _require(
                object_cells == {(x0 + dx, y0 + dy) for dx in range(width) for dy in range(length)},
                "Wrong equipment rectangle",
            )
    if "facility_bands" in info:
        traffic = {
            (x, y)
            for band in bands
            for x in range(band["traffic_x"], band["traffic_x"] + band["traffic_width"])
            for y in range(first, last + 2)
        }
        _require(not traffic & s.blocked, "Facility obstructs its reserved traffic band")


def dispatch_status(scenario, job, records, assigned, time):
    """Gate only currently released orders; assigned jobs lock a face until pickup ends.

    Derive each resource from the immutable task identity, never from an
    optional record.shelf supplied by a planner.
    """
    if not scenario.uses_layer_rules:
        return True, None
    jobs = {j.id: j for j in scenario.tasks}
    for record in records:
        previous = jobs.get(record["task_id"])
        if previous is None:
            raise ValueError("Unknown task in dispatch records")
        if previous.shelf == job.shelf and record["pickup_end"] > time:
            return False, "same_face_pickup_in_progress"
    contenders = [
        j
        for j in scenario.tasks
        if j.shelf == job.shelf and j.release <= time and j.id not in assigned
    ]
    first = min(contenders, key=lambda j: (-j.shelf_level, j.release, j.id), default=None)
    if first is not None and first.id != job.id:
        return False, "higher_layer_or_earlier_order_first"
    return True, None
