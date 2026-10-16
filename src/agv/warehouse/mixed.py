"""Reviewed V9 mixed-rack geometry, adapted from the teammate's V6/V9 model.

Only this explicit generated geometry family is accepted. The independently
rebuilt, task-free canonical geometry is also the metadata schema: unknown
fields or nested additions cannot carry seeds, future tasks or score references
into public observations. V4/legacy generators remain separate.

generate() preserves the historical finite-wait experiment family.
generate_current() activates the V9.1 publisher-close contract. Their scoring
references are versioned separately and must not be mixed.
"""

import json
import random
from functools import lru_cache

from agv.domain import Scenario, Task
from agv.warehouse.layout import connected


def _validate_options(mode, seed, task_count, vehicles, delivery_pattern, arrival, demand, horizon):
    for value, choices, label in (
        (mode, ("static", "dynamic"), "mode"),
        (delivery_pattern, ("distributed", "shared"), "delivery_pattern"),
        (arrival, ("batch", "uniform", "irregular", "burst"), "arrival"),
        (demand, ("balanced", "left_hotspot", "right_hotspot", "switching"), "demand"),
    ):
        if type(value) is not str or value not in choices:
            raise ValueError("Invalid " + label)
    for value, low, high, label in (
        (seed, 0, None, "seed"),
        (task_count, 0, None, "task_count"),
        (vehicles, 1, 10, "vehicles"),
    ):
        if type(value) is not int or value < low or (high is not None and value > high):
            raise ValueError("Invalid " + label)
    if horizon is not None and (type(horizon) is not int or horizon < 1):
        raise ValueError("Invalid horizon")


SIZES = {
    "medium": (46, 41, 3, 2, 3),
    "large": (62, 47, 4, 3, 4),
    "xlarge": (78, 65, 5, 3, 5),
    "xxlarge": (96, 69, 6, 4, 6),
}


def _build(
    *,
    mode="static",
    seed=0,
    task_count=12,
    vehicles=4,
    size="medium",
    delivery_pattern="distributed",
    arrival="batch",
    demand="balanced",
    horizon=None,
    aisle_width=2,
    work_width=2,
    obstacle_layout="columns_equipment",
    layout_variant=0,
    shelf_layers=3,
):
    if type(size) is not str or size not in SIZES:
        raise ValueError("未知仓库规格")
    if type(shelf_layers) is not int or not 3 <= shelf_layers <= 8:
        raise ValueError("货架层数必须为3到8层")
    if type(work_width) is not int or work_width not in (2, 3, 4):
        raise ValueError("作业通道宽度必须为2到4格")
    if type(aisle_width) is not int or aisle_width != 2:
        raise ValueError("基础连接间距参数为2格，实际间距由固定列中线和货架长度共同决定")
    if obstacle_layout != "columns_equipment":
        raise ValueError("本版固定中央设备和每个相邻间隔的立柱")
    if type(layout_variant) is not int or not 0 <= layout_variant <= 2:
        raise ValueError("布局编号为0到2")
    _validate_options(mode, seed, task_count, vehicles, delivery_pattern, arrival, demand, horizon)
    releases = []
    arrival_rng = random.Random(seed ^ 0xA771A1)
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
    width, _, cols, ni, no = SIZES[size]
    section_rows = {"medium": 4, "large": 4, "xlarge": 6, "xxlarge": 6}[size]
    outer_blank = {"medium": 2, "large": 3, "xlarge": 3, "xxlarge": 4}[size]
    equipment_blank = {"medium": 1, "large": 2, "xlarge": 3, "xxlarge": 4}[size]
    block_height = 1 + (section_rows - 1) * (2 + work_width)
    eh = 3 if size == "medium" else 5
    height = 2 * outer_blank + 2 * block_height + 2 * equipment_blank + eh + 6
    ey = outer_blank + block_height + equipment_blank + 3
    nominal_width = width + 1
    ew = max(7, nominal_width // 4)
    if ew % 2 != nominal_width % 2:
        ew += 1
    mid = height // 2
    homes = (
        [(0, 2 + round(k * (height - 5) / (vehicles - 1))) for k in range(vehicles)]
        if vehicles > 1
        else [(0, mid)]
    )

    def spread(n):
        return [3 + round(i * (width - 7) / (n - 1)) for i in range(n)]

    inlets = [(x, 0) for x in spread(ni)]
    stations = [(x, height - 1) for x in spread(no)]
    walls = (
        {(x, y) for x in range(width) for y in (0, height - 1)}
        | {(0, y) for y in range(height)}
        | {(width - 1, y) for y in range(height)}
    )
    walls -= set(homes) | set(stations)
    # Inlets are architectural illustrations only, closed to AGVs in this experiment.
    shelves = set()
    catalog = []
    pairs = []
    counter = 0

    def rack_pair(axis, start, length):
        nonlocal counter
        pair = "P" + str(len(pairs) + 1).zfill(2)
        faces = ("U", "D") if axis == "horizontal" else ("L", "R")
        groups = []
        for side, face in enumerate(faces):
            counter += 1
            group = f"R{counter:02d}"
            groups.append(group)
            for bay in range(length):
                x = start[0] + (bay if axis == "horizontal" else side)
                y = start[1] + (side if axis == "horizontal" else bay)
                loading = (
                    (x, y - 1 if side == 0 else y + 1)
                    if axis == "horizontal"
                    else (x - 1 if side == 0 else x + 1, y)
                )
                shelves.add((x, y))
                catalog.append(
                    dict(
                        position=[x, y],
                        loading_point=list(loading),
                        loading_points=[list(loading)],
                        rack_type="paired",
                        orientation=axis,
                        pair_id=pair,
                        face=face,
                        group_id=group,
                        bay=bay + 1,
                        bay_id=f"{group}-B{bay + 1:02d}",
                        levels=shelf_layers,
                    )
                )
        pairs.append(
            dict(
                pair_id=pair,
                orientation=axis,
                start=list(start),
                length=length,
                groups=groups,
                rack_type="paired",
            )
        )

    def single_row(start, length):
        nonlocal counter
        counter += 1
        group = f"R{counter:02d}"
        pair = "P" + str(len(pairs) + 1).zfill(2)
        for i in range(length):
            x, y = start[0] + i, start[1]
            points = [[x, y - 1], [x, y + 1]]
            shelves.add((x, y))
            catalog.append(
                dict(
                    position=[x, y],
                    loading_point=points[0],
                    loading_points=points,
                    rack_type="single",
                    orientation="horizontal",
                    pair_id=pair,
                    face="B",
                    group_id=group,
                    bay=i + 1,
                    bay_id=f"{group}-B{i + 1:02d}",
                    levels=1,
                )
            )
        pairs.append(
            dict(
                pair_id=pair,
                orientation="horizontal",
                start=list(start),
                length=length,
                groups=[group],
                rack_type="single",
            )
        )

    # Fixed, symmetric long-rack slots. Short racks shrink equally about these same centers.
    long_length = (nominal_width - 16 - 2 * (cols - 1) - (3 if cols % 2 == 0 else 0)) // cols
    if cols % 2 and long_length % 2 == 0:
        long_length -= 1
    short_length = long_length - 2
    if short_length < 3:
        raise ValueError("地图宽度不足")
    slot_gaps = [5 if cols % 2 == 0 and i == cols // 2 - 1 else 2 for i in range(cols - 1)]
    span = cols * long_length + sum(slot_gaps)
    left = (width - span - 7) // 2
    axis = left + (span - 1) / 2
    vx = left + span + 4
    ex = int(axis - (ew - 1) / 2)
    side_blank = left - 1
    slot_starts = []
    xx = left
    for col in range(cols):
        slot_starts.append(xx)
        xx += long_length + (slot_gaps[col] if col < cols - 1 else 0)
    centers = [x + (long_length - 1) / 2 for x in slot_starts]
    first = outer_blank + 2
    top_ys = [first] + [
        first + 1 + work_width + (i - 1) * (2 + work_width) for i in range(1, section_rows)
    ]
    bottom_start = ey + eh + equipment_blank + 1
    bottom_ys = [bottom_start] + [
        bottom_start + 1 + work_width + (i - 1) * (2 + work_width) for i in range(1, section_rows)
    ]
    row_layout = []
    row_starts = []
    for section, ys in enumerate((top_ys, bottom_ys)):
        for row, y in enumerate(ys):
            length = short_length if row < section_rows // 2 else long_length
            starts = [x + (long_length - length) // 2 for x in slot_starts]
            for x in starts:
                if row == 0:
                    single_row((x, y), length)
                else:
                    rack_pair("horizontal", (x, y), length)
            row_starts.append(starts)
            row_layout.append(
                dict(
                    section=section,
                    row=row,
                    y=y,
                    length=length,
                    rack_type="single" if row == 0 else "paired",
                )
            )
    for ys in (top_ys, bottom_ys):
        rack_pair("vertical", (vx, ys[0]), ys[-1] + 2 - ys[0])
    zones = {tuple(q) for v in catalog for q in v["loading_points"]}
    blocked = walls | shelves
    objects = []
    central_cells = [int(axis) - 1, int(axis), int(axis) + 1] if cols % 2 == 0 else []
    pillar_count = 1 if size in ("medium", "large") else 2
    pillar_rows = [int((k + 0.5) * section_rows / pillar_count) for k in range(pillar_count)]
    pillar_gap_indices = [
        i for i in range(cols - 1) if size in ("medium", "large") or i not in (1, 3)
    ]
    for row in row_layout:
        if row["row"] not in pillar_rows:
            continue
        y = row["y"] + (layout_variant % 2 if row["rack_type"] == "paired" else 0)
        for col in pillar_gap_indices:
            a = slot_starts[col] + long_length
            z = slot_starts[col + 1] - 1
            xs = [a if a < axis < z or z < axis else z]
            for x in xs:
                p = (x, y)
                if p in zones or p in blocked or x in central_cells:
                    raise ValueError("立柱与作业区或中央净通道冲突")
                blocked.add(p)
                objects.append(dict(kind="column", cells=[list(p)]))
    cells = {(x, y) for x in range(ex, ex + ew) for y in range(ey, ey + eh)}
    if cells & (shelves | zones | walls):
        raise ValueError("设备区与服务区域重叠")
    blocked |= cells
    objects.append(dict(kind="equipment", cells=[list(p) for p in sorted(cells)]))
    if not connected(width, height, blocked):
        raise ValueError("生成地图不连通")
    free = {(x, y) for x in range(width) for y in range(height)} - blocked
    transit = free - zones - set(homes) - set(stations)
    positions = random.Random(seed)
    bias = random.Random(seed ^ 0xD3A4AD)
    layers = random.Random(seed ^ 0x1A7E)
    left_s = sorted(p for p in shelves if p[0] < width / 2)
    right_s = sorted(shelves - set(left_s))
    tasks = []
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
        shelf = positions.choice(right_s if side else left_s)
        destination = positions.choice(stations) if delivery_pattern != "shared" else stations[0]
        level = layers.randint(
            1, next(v["levels"] for v in catalog if tuple(v["position"]) == shelf)
        )
        tasks.append(
            Task(j, None, destination, release, 2 * level, 1, shelf=shelf, shelf_level=level)
        )
    info = dict(
        kind="mixed-v5",
        model_version="mixed-v9",
        finish_policy="return_home",
        idle_policy="standby_near_delivery",
        geometry_layout="balanced_side_single_paired_rows",
        rules_version="delivery-only-v1",
        station_access="delivery_only",
        service_rule="2l",
        objective_weights=[0.5, 0.3, 0.2],
        size=size,
        rows=len(top_ys + bottom_ys),
        columns=cols,
        horizontal_axis=axis,
        side_blank_width=side_blank,
        horizontal_vertical_blank_width=3,
        horizontal_envelope=[left, left + span - 1],
        right_vertical_x=vx,
        alignment="column_centers",
        layout_revision="v8.1_selected_column_gaps",
        pillar_gap_indices=pillar_gap_indices,
        pillar_rule="sparse_selected_gaps",
        pillars_per_gap_section=pillar_count,
        pillar_rows_per_section=pillar_rows,
        column_centers=centers,
        outer_blank_width=outer_blank,
        equipment_blank_width=equipment_blank,
        central_clear_width=3 if cols % 2 == 0 else 0,
        central_clear_columns=central_cells,
        row_layout=row_layout,
        section_rows=section_rows,
        short_length=short_length,
        long_length=long_length,
        single_bay_capacity=1,
        layer_count=shelf_layers,
        loading_rule="independent_sides",
        side_capacity=1,
        layer_order="descending_per_face",
        rack_catalog=catalog,
        rack_pairs=pairs,
        inbound_ports=[list(p) for p in inlets],
        inbound_access="illustration_only_blocked",
        outbound_ports=[list(p) for p in stations],
        boundary_walls=[list(p) for p in sorted(walls)],
        aisle_width=2,
        work_width=work_width,
        base_aisle_width=2,
        base_work_width=work_width,
        perimeter_left=side_blank,
        perimeter_right=side_blank,
        perimeter_top=outer_blank,
        perimeter_bottom=outer_blank,
        layout_variant=layout_variant,
        obstacle_layout=obstacle_layout,
        obstacles=objects,
        equipment_rect=[ex, ey, ew, eh],
        equipment_footprint=[ew, eh],
        equipment_side="rack_axis",
        column_count=sum(o["kind"] == "column" for o in objects),
        equipment_count=sum(o["kind"] == "equipment" for o in objects),
        obstacle_cells=sum(len(o["cells"]) for o in objects),
        description="水平与竖直背靠背货架，前半短后半长、首排单排一层；中央设备；左侧H，上方入库示意，下方出库交付",
    )
    return Scenario(
        width,
        height,
        blocked,
        shelves,
        homes,
        tasks,
        horizon,
        service_axis="catalog",
        pickup_zones=zones,
        transit_only=transit,
        stations=stations,
        map_info=info,
    )


def generate(**options):
    """Build an explicit mixed-v9 scenario; default size medium, 3 paired layers."""
    return _build(**options).check()


@lru_cache(maxsize=32)
def _canonical(size, vehicles, layers, work_width, variant):
    return _build(
        size=size,
        vehicles=vehicles,
        shelf_layers=layers,
        work_width=work_width,
        layout_variant=variant,
        task_count=0,
    )


def validate_profile(scenario):
    """Validate every static field against this declared V9 geometry revision.

    Different/custom warehouse geometries need their own explicit profile;
    silently treating their metadata as this generated family is disallowed.
    Task release times and identities are checked separately by Scenario.
    """
    s = scenario
    info = s.map_info
    if (
        info.get("model_version") not in ("mixed-v9", "mixed-v9.1")
        or type(info.get("size")) is not str
        or info["size"] not in SIZES
    ):
        raise ValueError("Unsupported V9 model or size")
    for key, low, high in (("layer_count", 3, 8), ("work_width", 2, 4), ("layout_variant", 0, 2)):
        value = info.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Invalid V9 " + key)
    if not 1 <= len(s.homes) <= 10:
        raise ValueError("V9 needs 1 to 10 vehicles")
    expected = _canonical(
        info["size"], len(s.homes), info["layer_count"], info["work_width"], info["layout_variant"]
    )
    for field in (
        "width",
        "height",
        "blocked",
        "shelves",
        "homes",
        "service_axis",
        "pickup_zones",
        "transit_only",
        "stations",
    ):
        if getattr(s, field) != getattr(expected, field):
            raise ValueError("V9 geometry differs from declared revision: " + field)
    try:
        actual = json.dumps(info, sort_keys=True, separators=(",", ":"), allow_nan=False)
        target = json.dumps(
            {**expected.map_info, "model_version": info["model_version"]},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid V9 metadata") from error
    if actual != target:
        raise ValueError("Unknown or inconsistent V9 metadata, catalog or facilities")


def generate_current(*, order_stream_end=None, **options):
    """V9.1 business contract; generate() retains historical V9 experiments."""
    scene = _build(**options)
    scene.map_info["model_version"] = "mixed-v9.1"
    scene.order_stream_end = (
        max((j.release for j in scene.tasks), default=0)
        if order_stream_end is None
        else order_stream_end
    )
    return scene.check()
