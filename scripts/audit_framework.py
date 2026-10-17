"""Deterministic framework matrix and archived-trace re-audit, not algorithm tuning."""

import argparse
import csv
import hashlib
import itertools
import json
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

from agv.dispatch.registry import run_raw
from agv.domain import Scenario
from agv.evaluation.objective import _SCORE_FIELDS
from agv.evaluation.validation import validate
from agv.warehouse.mixed import generate_current

ROOT = Path(__file__).resolve().parents[1]
SIZES = ("medium", "large", "xlarge", "xxlarge")


def source_hashes():
    files = list((ROOT / "src").rglob("*.py")) + [Path(__file__)]
    files += [ROOT / "src/agv/web/static/app.js"]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(
            p.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for p in sorted(files)
    }


def geometry_matrix():
    rows = []
    for size, cars, layers, width, variant in itertools.product(
        SIZES, (1, 10), (3, 8), (2, 4), (0, 1, 2)
    ):
        s = generate_current(
            size=size,
            vehicles=cars,
            shelf_layers=layers,
            work_width=width,
            layout_variant=variant,
            task_count=0,
        )
        assert Scenario.from_dict(s.to_dict()).to_dict() == s.to_dict()
        # Independent connectivity walk: no traversal through D or another car's H.
        forbidden = set(s.homes[1:]) | set(s.stations)
        reached, queue = {s.homes[0]}, deque([s.homes[0]])
        while queue:
            x, y = queue.popleft()
            for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if s.free(p) and p not in reached and p not in forbidden:
                    reached.add(p)
                    queue.append(p)
        for rack in s.map_info["rack_catalog"]:
            assert all(tuple(p) in reached for p in rack["loading_points"])
            if rack["rack_type"] == "single":
                assert rack["levels"] == 1 and len(rack["loading_points"]) == 2
            else:
                assert rack["levels"] == layers and len(rack["loading_points"]) == 1
        for x, y in s.stations:
            assert any(p in reached for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        rows.append(dict(size=size, cars=cars, layers=layers, work_width=width, variant=variant))
    return rows


def execution_case(spec):
    size, case, solver = spec
    params = dict(size=size, seed=4701, task_count=4, vehicles=1)
    if case == "capacity_layers":
        params.update(task_count=10, vehicles=10, shelf_layers=8, delivery_pattern="shared")
    elif case == "dynamic":
        params.update(task_count=8, vehicles=4, shelf_layers=8, mode="dynamic", arrival="uniform")
    s = generate_current(**params)
    if case == "capacity_layers":
        catalog = {tuple(r["position"]): r for r in s.map_info["rack_catalog"]}
        s.tasks = [
            replace(
                j,
                shelf_level=catalog[j.shelf]["levels"],
                pickup_service=2 * catalog[j.shelf]["levels"],
            )
            for j in s.tasks
        ]
    if case == "dynamic":
        s.tasks = [replace(j, release=j.release * 10) for j in s.tasks]
        s.order_stream_end = max(j.release for j in s.tasks) + 20
    r = run_raw(solver, s.check())
    assert r["feasible"] and validate(s, r), (size, case, solver, r.get("reason"))
    return dict(
        size=size,
        case=case,
        solver=solver,
        vehicles=len(s.homes),
        tasks=len(s.tasks),
        time=r["time"],
        T=r["makespan"],
        R=r["mean_flow_time"],
        D=r["moves"],
        energy=0.05 * r["moves"],
        valid=True,
    )


def archives(root):
    traces, tables = [], []
    for p in sorted(root.rglob("traces/*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        s = Scenario.from_dict(data["scenario"])
        result = {k: v for k, v in data["result"].items() if k not in _SCORE_FIELDS}
        try:
            validate(s, result)
            traces.append(dict(file=str(p.relative_to(root)), valid=True))
        except Exception as error:
            traces.append(
                dict(
                    file=str(p.relative_to(root)),
                    valid=False,
                    error=f"{type(error).__name__}: {error}",
                )
            )
    for p in sorted(root.rglob("runs.csv")):
        with p.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        checked = 0
        for row in rows:
            if row.get("score_valid", "").lower() != "true":
                continue
            f = 0.5 * float(row["makespan"]) / float(row["reference_T"])
            f += 0.3 * float(row["mean_flow_time"]) / float(row["reference_R"])
            f += 0.2 * float(row["moves"]) / float(row["reference_D"])
            assert abs(f - float(row["weighted_score"])) < 1e-10
            checked += 1
        tables.append(dict(file=str(p.relative_to(root)), rows=len(rows), scores_checked=checked))
    return dict(
        traces=traces,
        tables=tables,
        limitation="Only retained traces audited; CSV arithmetic is not a rerun of all executions or A* references.",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a fresh output path")
    sources = source_hashes()
    report = dict(base_commit="ff0d8b713d9f9ddaef2b17b0e75e1bf9c55b8ebe", source_lf_sha256=sources)
    report["geometry"] = geometry_matrix()
    print("geometry", len(report["geometry"]), flush=True)
    if args.archives:
        report["archives"] = archives(args.archives)
        print("retained traces", len(report["archives"]["traces"]), flush=True)
    specs = list(
        itertools.product(
            SIZES,
            ("sequential", "capacity_layers", "dynamic"),
            ("sipp_position_delay_dispatch", "sipp_stream_bcrd_tail"),
        )
    )
    report["executions"] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(execution_case, specs):
            report["executions"].append(row)
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(row["size"], row["case"], row["solver"], "valid", flush=True)
    assert source_hashes() == sources, "Source changed during audit"
    report["completed"] = True
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
