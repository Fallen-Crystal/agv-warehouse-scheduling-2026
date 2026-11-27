"""Build the course-report inputs from the published WEPA source and report §3."""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "recommended-20261024" / "data" / "raw"
ORDER_SHA256 = "caab14a69aa34734f3ceb04f6c595f712b7dc4a1ee65adbe92268a16a7159432"
STOCK_SHA256 = "9f2237b8dab891d51b6925242a6691f9af826c58b0a1c09a92ad0fb8fb9ec92c"

# (start in source seconds, duration, inbound, outbound, SKU count).
MAIN = {
    "day5": (265 * 1800, 1800, 22, 33, 1),
    "day19": (932 * 1800, 1800, 78, 66, 4),
    "day53": (2571 * 1800, 1800, 19, 66, 1),
    "day55": (1336 * 3600, 3600, 56, 33, 1),
    "day76": (3677 * 1800, 1800, 28, 66, 1),
}
SUPPLEMENT = {
    "day54": (1311 * 3600, 3600, 31, 14, 3),
    "day59": (1430 * 3600, 3600, 42, 8, 2),
    "day83": (2006 * 3600, 3600, 84, 102, 5),
}
WINDOWS = MAIN | SUPPLEMENT
SIZES = {f"size{n}": n for n in range(6, 37, 6)}
PROTOCOL = {
    "configuration": {"size": "large", "vehicles": 6, "layers": 5},
    "objective": {
        "version": "linear-physical-v2-20261024",
        "horizon_seconds": 900.0,
        "vehicles": 6,
        "speed_cells_per_second": 1.0,
        "seconds_per_step": 1.0,
        "weights": [0.5, 0.3, 0.2],
    },
}


def checked_json(path, expected_sha256):
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError(f"WEPA source hash mismatch: {path.name}")
    return json.loads(data)


def real_case(name):
    start, duration, inbound, outbound, n_skus = WINDOWS[name]
    end = start + duration
    rows = checked_json(RAW / "2_orders.json.gz", ORDER_SHA256)
    stock = Counter({int(k): v for k, v in checked_json(
        RAW / "3_initial_fill_lvl.json", STOCK_SHA256
    ).items()})
    tasks = []
    for index, (kind, sku, timestamp, dock, batch, week) in enumerate(rows):
        if timestamp < start:
            stock[sku] += 1 if kind == "delivery" else -1
        elif timestamp < end:
            tasks.append({
                "id": len(tasks), "source_row": index, "kind": kind, "sku": sku,
                "release": timestamp - start, "source_time": timestamp,
                "source_dock": dock, "batch": batch, "week": week,
            })
    skus = sorted({task["sku"] for task in tasks})
    if len(skus) != n_skus or Counter(t["kind"] for t in tasks) != {
        "delivery": inbound, "retrieval": outbound
    }:
        raise ValueError(f"Unexpected order composition for {name}")
    initial = {str(sku): stock[sku] for sku in skus}
    return {"case": name, "start_seconds": start, "end_seconds": end,
            "close_at": duration, "initial": initial, "tasks": tasks}


def synthetic_case(name):
    count = SIZES[name]
    tasks = [
        {"id": i, "sku": 101, "release": 0, "source_dock": i % 3 + 1,
         "kind": "retrieval" if i % 2 == 0 else "delivery"}
        for i in range(count)
    ]
    return {"case": name, "close_at": 1, "initial": {"101": 36}, "tasks": tasks}


def load_case(name):
    return real_case(name) if name in WINDOWS else synthetic_case(name)
