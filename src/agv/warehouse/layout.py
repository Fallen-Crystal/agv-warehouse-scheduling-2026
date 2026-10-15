"""Structured V4 warehouse generator adapted from the teammate's delivery.

Independent random streams preserve the exact supplied V4 scene identity.
No simulation, legacy scene construction or global RNG mutation is needed.
"""

import random
from collections import deque

from agv.domain import Scenario, Task

SIZES = {
    "small": (3, 3, 5),
    "medium": (4, 4, 6),
    "large": (6, 4, 8),
    "xlarge": (8, 6, 8),
    "xxlarge": (10, 7, 9),
}
SCALE = {name: i for i, name in enumerate(SIZES)}


def connected(width, height, blocked):
    free = {(x, y) for x in range(width) for y in range(height)} - blocked
    if not free:
        return False
    seen = {next(iter(free))}
    q = deque(seen)
    while q:
        x, y = q.popleft()
        for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if p in free and p not in seen:
                seen.add(p)
                q.append(p)
    return len(seen) == len(free)


def generate(
    *,
    mode="static",
    seed=0,
    task_count=12,
    vehicles=4,
    size="small",
    delivery_pattern="distributed",
    arrival="batch",
    demand="balanced",
    horizon=None,
    aisle_width=2,
    work_width=2,
    obstacle_layout="none",
    layout_variant=0,
    shelf_layers=3,
):
    if type(size) is not str or size not in SIZES:
        raise ValueError("未知货架规模")
    if mode not in ("static", "dynamic"):
        raise ValueError("Unknown task mode")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if type(task_count) is not int or task_count < 0:
        raise ValueError("task_count must be nonnegative")
    if type(vehicles) is not int or not 1 <= vehicles <= 10:
        raise ValueError("vehicles must be 1 to 10")
    if horizon is not None and (type(horizon) is not int or horizon < 1):
        raise ValueError("Invalid horizon")
    if delivery_pattern not in ("distributed", "shared"):
        raise ValueError("Unknown delivery pattern")
    if arrival not in ("batch", "uniform", "irregular", "burst"):
        raise ValueError("Unknown arrival pattern")
    if demand not in ("balanced", "left_hotspot", "right_hotspot", "switching"):
        raise ValueError("Unknown demand pattern")
    if type(aisle_width) is not int or aisle_width != 2:
        raise ValueError("连接通道总宽固定为2格（含立柱）")
    if type(work_width) is not int or work_width not in (2, 3, 4):
        raise ValueError("作业通道宽度应为2、3、4格")
    if obstacle_layout not in ("none", "columns", "columns_equipment"):
        raise ValueError("未知建筑障碍方案")
    if type(layout_variant) is not int or not 0 <= layout_variant <= 2:
        raise ValueError("布局编号为0、1、2")
    if type(shelf_layers) is not int or not 1 <= shelf_layers <= 5:
        raise ValueError("货架层数为1到5层")
    arrival_rng = random.Random(seed ^ 0xA771A1)
    releases = []
    release = 0
    for j in range(task_count):
        if arrival == "batch":
            release = (j // 3) * 15
        elif arrival == "uniform":
            release = j * 5
        elif arrival == "irregular":
            release = 0 if j == 0 else release + arrival_rng.randint(1, 9)
        else:
            release = (j // 6) * 30
        releases.append(0 if mode == "static" else release)
    rows, columns, length = SIZES[size]
    increment = SCALE[size]
    actual_aisle = 2
    actual_work = work_width
    perimeter = 3 if increment < 2 else 4
    # The selected width includes the column: no extra grid column is inserted.
    facility_gaps = (
        [c for c in range(columns - 1) if (c + layout_variant) % 2 == 0]
        if obstacle_layout != "none"
        else []
    )
    reserve = 1
    starts = [perimeter]
    for c in range(columns - 1):
        starts.append(starts[-1] + length + actual_aisle)
    facility_bands = [
        dict(
            connector=c,
            x=starts[c] + length + actual_aisle - 1,
            width=reserve,
            traffic_x=starts[c] + length,
            traffic_width=actual_aisle - 1,
        )
        for c in facility_gaps
    ]
    ys = [perimeter + 1 + r * (2 + actual_work) for r in range(rows)]
    equipment_strip = 0
    equipment_x = starts[-1] + length
    width = equipment_x + equipment_strip + perimeter
    height = ys[-1] + 1 + perimeter + 1
    homes = (
        [(width // 2, 0)]
        if vehicles == 1
        else [(2 + round(k * (width - 5) / (vehicles - 1)), 0) for k in range(vehicles)]
    )
    stations = [(1, 1), (width - 2, 1), (1, height - 1), (width - 2, height - 1)]
    shelves = {
        (x, y)
        for top in ys
        for y in (top, top + 1)
        for start in starts
        for x in range(start, start + length)
    }
    zones = {(x, y + dy) for x, y in shelves for dy in (-1, 1) if (x, y + dy) not in shelves}
    base = shelves | {(x, 0) for x in range(width) if (x, 0) not in homes}
    obstacles = []
    blocked = set(base)
    # Facilities are in explicit reserved strips, never in the adjacent traffic band.
    for band in facility_bands:
        x = band["x"]
        for r in range(layout_variant // 2, rows, 2):
            cells = {(x, ys[r])}
            if connected(width, height, blocked | cells):
                blocked |= cells
                obstacles.append(dict(kind="column", cells=[list(p) for p in sorted(cells)]))
    equipment_width = 1 if increment < 2 else 2
    equipment_length = 3 if increment < 2 else 2 * max(2, round(height / 10)) + 1
    # Edge equipment follows the user-marked outermost left/right locations.
    if obstacle_layout == "columns_equipment":
        center = (ys[0] + ys[-1] + 1) // 2
        for x in (0, width - equipment_width):
            cells = {
                (x + dx, y)
                for dx in range(equipment_width)
                for y in range(center - equipment_length // 2, center + equipment_length // 2 + 1)
            }
            if cells & (zones | set(stations) | set(homes) | blocked):
                continue
            if connected(width, height, blocked | cells):
                blocked |= cells
                obstacles.append(dict(kind="equipment", cells=[list(p) for p in sorted(cells)]))
    free = {(x, y) for x in range(width) for y in range(height)} - blocked
    transit = free - zones - set(homes) - set(stations)
    left = sorted(p for p in shelves if p[0] < width / 2)
    right = sorted(shelves - set(left))
    positions = random.Random(seed)
    bias = random.Random(seed ^ 0xD3A4AD)
    tasks = []
    catalog = []
    for r, y in enumerate(ys):
        for c, start in enumerate(starts):
            pair = f"P{r * columns + c + 1:02d}"
            for side, dy in [("U", 0), ("D", 1)]:
                group = f"R{(r * 2 + dy) * columns + c + 1:02d}"
                for bay, x in enumerate(range(start, start + length)):
                    catalog.append(
                        dict(
                            position=[x, y + dy],
                            pair_id=pair,
                            face=side,
                            group_id=group,
                            bay=bay + 1,
                            bay_id=f"{group}-B{bay + 1:02d}",
                            levels=shelf_layers,
                        )
                    )
    layer_rng = random.Random(seed ^ 0x1A7E)
    for j, release in enumerate(releases):
        side = positions.randrange(2)
        if demand != "balanced":
            hot = (
                1
                if demand == "right_hotspot"
                or (demand == "switching" and j >= (task_count + 1) // 2)
                else 0
            )
            side = hot if bias.random() < 0.8 else 1 - hot
        shelf = positions.choice(right if side else left)
        destination = positions.choice(stations)
        if delivery_pattern == "shared":
            destination = stations[0]
        tasks.append(
            Task(
                j,
                None,
                destination,
                release,
                pickup_service=2 * (level := layer_rng.randint(1, shelf_layers)),
                delivery_service=1,
                shelf=shelf,
                shelf_level=level,
            )
        )
    info = dict(
        model_version="math-v4-integrated",
        service_rule="2l",
        objective_weights=[0.5, 0.3, 0.2],
        kind="structured-v1",
        size=size,
        rows=rows,
        columns=columns,
        shelf_length=length,
        shelf_thickness=2,
        rules_version="delivery-only-v1",
        station_access="delivery_only",
        geometry_layout="paired_rows",
        layer_order="descending_per_face",
        base_aisle_width=aisle_width,
        base_work_width=work_width,
        aisle_width=actual_aisle,
        work_width=actual_work,
        scale_increment=0,
        rack_catalog=catalog,
        layer_count=shelf_layers,
        loading_rule="independent_sides",
        side_capacity=1,
        perimeter_left=perimeter,
        perimeter_right=perimeter,
        perimeter_top=perimeter - 1,
        perimeter_bottom=perimeter - 1,
        removed_empty_rows=2,
        obstacle_layout=obstacle_layout,
        layout_variant=layout_variant,
        obstacles=obstacles,
        facility_bands=facility_bands,
        facility_reserved_width=0,
        aisle_width_includes_columns=True,
        aisle_clear_at_columns=actual_aisle - 1,
        equipment_side="both_edges",
        equipment_strip_width=0,
        equipment_strip_x=equipment_x,
        equipment_footprint=[equipment_width, equipment_length],
        perimeter_clear_at_equipment=perimeter - equipment_width,
        column_count=sum(o["kind"] == "column" for o in obstacles),
        equipment_count=sum(o["kind"] == "equipment" for o in obstacles),
        obstacle_cells=sum(len(o["cells"]) for o in obstacles),
    )
    return Scenario(
        width,
        height,
        blocked,
        shelves,
        homes,
        tasks,
        horizon,
        service_axis="north_south",
        pickup_zones=zones,
        transit_only=transit,
        stations=stations,
        map_info=info,
    ).check()
