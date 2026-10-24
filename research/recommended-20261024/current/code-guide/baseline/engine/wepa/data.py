"""Frozen, input-selected complete pallet requests from WEPAStacks."""
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from agv.warehouse.mixed import generate_current


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(root):
    root = Path(root)
    raw = root / "data/raw"
    rows = json.loads((raw / "2_orders.json").read_text())
    stock = Counter({int(k): v for k, v in json.loads(
        (raw / "3_initial_fill_lvl.json").read_text()).items()})
    bins = defaultdict(list)
    for i, row in enumerate(rows):
        bins[row[2] // 900].append((i, row))
    selected, days = [], set()
    # Input-only criteria fixed before solving. One earliest qualifying window per day.
    for bucket, entries in bins.items():
        kinds = Counter(row[0] for _, row in entries)
        skus = sorted({row[1] for _, row in entries})
        initial = {s: stock[s] for s in skus}
        day = bucket // 96
        if (35 <= len(entries) <= 65 and len(kinds) == 2 and 2 <= len(skus) <= 5
                and sum(initial.values()) <= 900 and day not in days):
            # Every outbound batch is at one timestamp in this source. Half-open time
            # windows preserve all rows at that timestamp; never truncate at row N.
            tasks = [dict(id=j, source_row=i, kind=r[0], sku=r[1],
                          release=r[2] - bucket * 900, source_time=r[2],
                          source_dock=r[3], batch=r[4], week=r[5])
                     for j, (i, r) in enumerate(entries)]
            # Require a source-feasible closed working-area ledger.
            check = Counter(initial)
            for task in tasks:
                check[task["sku"]] += 1 if task["kind"] == "delivery" else -1
            if all(v >= 0 for v in check.values()):
                selected.append(dict(case=f"wepa-day{day}-bin{bucket}", source_day=day,
                    source_bin=bucket, start_seconds=bucket * 900,
                    end_seconds=(bucket + 1) * 900, close_at=900,
                    initial={str(k): v for k, v in initial.items()}, tasks=tasks))
                days.add(day)
                if len(selected) == 6:
                    break
        for _, row in entries:
            stock[row[1]] += 1 if row[0] == "delivery" else -1
    if len(selected) != 6:
        raise ValueError("Not enough input-eligible windows")
    protocol = dict(version="wepa-mixed-1", source_sha256=digest(raw / "2_orders.json"),
        window_seconds=900, seconds_per_step=1, layers=5, primary_vehicles=6,
        parking_capacity=8, mapping_seed=17, candidate_budget=6,
        methods=["fcfs", "eta", "joint"], cpu_seconds=120,
        development=[s["case"] for s in selected[:3]],
        heldout=[s["case"] for s in selected[3:]],
        selection="lowest mean paired F on development; any invalid disqualifies; CPU breaks ties",
        geometry="reviewed generator, eight fixed home positions, inbound terminals opened",
        initial_rule="full source ledger at window start for selected SKUs; all earlier operations assumed complete",
        limits="source arrivals, synthetic shelf locations and unit-time motion; no original-plant reproduction",
        cases=selected)
    target = root / "data/protocol.json"
    if target.exists():
        if json.loads(target.read_text()) != protocol:
            raise ValueError("Refuse to alter frozen protocol")
    else:
        target.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return protocol


def geometry(size="large", layers=5):
    scene = generate_current(size=size, vehicles=8, shelf_layers=layers, task_count=0)
    # Validate the reviewed geometry before opening the existing illustrative inlets.
    scene.check()
    inlets = [tuple(p) for p in scene.map_info["inbound_ports"]]
    outlets = list(scene.stations)
    scene.blocked.difference_update(inlets)
    scene.stations = inlets + outlets
    scene.horizon = None
    return scene, inlets, outlets


def build(case, size="large", layers=5, vehicles=6):
    if vehicles not in (1, 2, 4, 6, 8):
        raise ValueError("Unsupported fixed fleet")
    scene, inlets, outlets = geometry(size, layers)
    rng = random.Random(17)
    bays = [dict(r) for r in scene.map_info["rack_catalog"]]
    rng.shuffle(bays)
    initial = {int(k): v for k, v in case["initial"].items()}
    owners, assigned, used = {}, defaultdict(list), set()
    # Fixed stocking allowance, independent of future demand counts.
    for sku in sorted(initial):
        needed = initial[sku] + 50
        for i, bay in enumerate(bays):
            pair = (bay["pair_id"], bay["bay"])
            if i in used or owners.get(pair) == sku:
                continue
            used.add(i)
            owners[pair] = sku
            assigned[sku].append(bay)
            needed -= bay["levels"]
            if needed <= 0:
                break
        if needed > 0:
            raise ValueError("Selected source stock exceeds legal mapped shelf capacity")
    slots, occupied = [], set()
    for sku in sorted(initial):
        available = []
        for bay in assigned[sku]:
            for level in range(1, bay["levels"] + 1):
                sid = len(slots)
                slots.append(dict(id=sid, sku=sku, bay=bay["bay_id"],
                    shelf=tuple(bay["position"]), level=level,
                    points=[tuple(p) for p in bay["loading_points"]]))
                available.append(sid)
        occupied.update(available[:initial[sku]])
    tasks = []
    for raw in case["tasks"]:
        task = dict(raw)
        ports = inlets if task["kind"] == "delivery" else outlets
        task["port"] = ports[(task["source_dock"] - 1) % len(ports)]
        tasks.append(task)
    return dict(case=case["case"], scene=scene, inlets=inlets, outlets=outlets,
                slots=slots, occupied=occupied, tasks=tasks, close_at=case["close_at"],
                vehicles=vehicles, size=size, layers=layers)
