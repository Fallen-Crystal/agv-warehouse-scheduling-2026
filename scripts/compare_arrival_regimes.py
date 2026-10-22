"""Matched eight-job workloads: change only release/closure timing."""

import argparse
import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from statistics import mean
from time import process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.path_research import run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


def worker(case):
    size, seed, variants, out = case
    dynamic = generate_current(
        size=size,
        seed=seed,
        vehicles=4,
        task_count=8,
        mode="dynamic",
        arrival="burst",
        horizon=None,
        shelf_layers=8,
    )
    static = Scenario.from_dict(dynamic.to_dict())
    static.tasks = [replace(j, release=0) for j in static.tasks]
    static.order_stream_end = 0
    static.check()
    scenes = dict(static=static, dynamic=dynamic)
    for mode, scene in scenes.items():
        Path(out, "scenes", f"{size}-{mode}-{seed}.json").write_text(
            json.dumps(scene.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
    jobs = [(m, v) for m in scenes for v in variants]
    shift = seed % len(jobs)
    rows = []
    for mode, variant in jobs[shift:] + jobs[:shift]:
        orders, route = variant.split("__")
        scene = scenes[mode]
        row = dict(map=size, mode=mode, seed=seed, variant=variant, optimizer_seed=0)
        start = process_time()
        try:
            raw = run(scene, route=route, orders=orders)
            row["cpu_seconds"] = process_time() - start
            result = score_result(scene, raw)
            validate(scene, result)
            if not result["score_valid"]:
                raise ValueError("Incomplete matched workload")
            row.update(
                valid=True,
                F=result["weighted_score"],
                T=result["makespan"],
                R=result["mean_flow_time"],
                D=result["moves"],
            )
            Path(out, "traces", f"{size}-{mode}-{seed}-{variant}.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as error:
            row.update(valid=False, error=f"{type(error).__name__}: {error}")
        rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    selection = json.loads(a.selection.read_text(encoding="utf-8"))
    variants = list(dict.fromkeys(["portfolio__sipp", selection["static"], selection["dynamic"]]))
    a.output.mkdir(parents=True, exist_ok=False)
    for name in ("scenes", "traces"):
        (a.output / name).mkdir()
    before = fingerprints()
    protocol = dict(
        source_sha256=before,
        selection_sha256=hashlib.sha256(a.selection.read_bytes()).hexdigest(),
        seeds=[8150, 8151],
        variants=variants,
        maps=["medium", "large", "xlarge", "xxlarge"],
        tasks=8,
        vehicles=4,
        role="diagnostic only; no retuning or selection",
        difference="release and stream closure timing only",
    )
    (a.output / "freeze.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    rows = []
    cases = [(m, s, variants, str(a.output)) for m in protocol["maps"] for s in protocol["seeds"]]
    with (a.output / "rows.jsonl").open("w", encoding="utf-8") as log:
        with ProcessPoolExecutor(max_workers=2) as pool:
            for future in as_completed([pool.submit(worker, c) for c in cases]):
                for row in future.result():
                    rows.append(row)
                    log.write(json.dumps(row) + "\n")
                log.flush()
                print(
                    json.dumps(dict(runs=len(rows), valid=sum(r["valid"] for r in rows))),
                    flush=True,
                )
    if before != fingerprints():
        raise ValueError("Source changed")
    with (a.output / "runs.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)
    base = {
        (r["map"], r["mode"], r["seed"]): r
        for r in rows
        if r["variant"] == "portfolio__sipp" and r["valid"]
    }
    summary = dict(
        runs=len(rows), valid=sum(r["valid"] for r in rows), source_unchanged=True, by_variant={}
    )
    if summary["valid"] == summary["runs"]:
        for v in variants:
            summary["by_variant"][v] = {
                mode: mean(
                    100 * (1 - r["F"] / base[r["map"], mode, r["seed"]]["F"])
                    for r in rows
                    if r["variant"] == v and r["mode"] == mode
                )
                for mode in ("static", "dynamic")
            }
    (a.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
