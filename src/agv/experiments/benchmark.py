"""Paired full-simulation ablations, bounded outputs and auditable provenance."""

import csv
import hashlib
import json
import platform
import statistics
import time
from functools import partial
from pathlib import Path

from agv.dispatch.registry import SOLVERS, run_named
from agv.domain import example
from agv.evaluation.validation import validate
from agv.io.movingai import derived_scene
from agv.io.scenes import pack_scene, scenario_id
from agv.io.storage import write_json

CONFIGS = {
    "static_small_wide": dict(
        mode="static", size="small", vehicles=4, layout="wide", task_count=12
    ),
    "static_small_bottleneck": dict(
        mode="static", size="small", vehicles=4, layout="bottleneck", task_count=12
    ),
    "dynamic_medium_burst": dict(
        mode="dynamic",
        size="medium",
        vehicles=6,
        layout="bottleneck",
        task_count=30,
        arrival="burst",
    ),
    "dynamic_large_shared": dict(
        mode="dynamic",
        size="large",
        vehicles=8,
        layout="bottleneck",
        task_count=40,
        arrival="irregular",
        delivery_pattern="shared",
    ),
    "dynamic_small_switching": dict(
        mode="dynamic",
        size="small",
        vehicles=4,
        layout="bottleneck",
        task_count=30,
        arrival="irregular",
        demand="switching",
    ),
    "short_horizon_stress": dict(
        mode="static", size="medium", vehicles=6, layout="bottleneck", task_count=30, horizon=100
    ),
}
DEFAULT_SOLVERS = (
    "baseline",
    "joint_only",
    "sipp_joint",
    "sipp_conflict",
    "sipp_budget",
    "sipp_learned",
)
FIELDS = (
    "makespan",
    "mean_flow_time",
    "p90_flow_time",
    "moves",
    "empty_moves",
    "loaded_moves",
    "traffic_wait_steps",
)


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in (".py", ".json", ".js", ".html", ".css")
    }


def summarize(rows):
    summaries = []
    for name in dict.fromkeys(r["scenario"] for r in rows):
        original = {
            r["seed"]: r for r in rows if r["scenario"] == name and r["solver"] == "baseline"
        }
        for solver in dict.fromkeys(r["solver"] for r in rows):
            own = [r for r in rows if r["scenario"] == name and r["solver"] == solver]
            paired = [
                (original[r["seed"]], r)
                for r in own
                if r["feasible"] and original[r["seed"]]["feasible"]
            ]
            item = dict(
                scenario=name,
                solver=solver,
                runs=len(own),
                successes=sum(r["feasible"] for r in own),
                completed_mean=statistics.mean(r["completed"] for r in own),
                paired_successes=len(paired),
                runtime_mean=statistics.mean(r["runtime_seconds"] for r in own),
                runtime_std=statistics.stdev(r["runtime_seconds"] for r in own)
                if len(own) > 1
                else None,
                expanded_mean=statistics.mean(r["expanded"] for r in own),
                replan_calls_mean=statistics.mean(r["replan_calls"] for r in own),
                accepted_replans_mean=statistics.mean(r["accepted_replans"] for r in own),
            )
            for field in FIELDS:
                a = [base[field] for base, r in paired]
                b = [r[field] for base, r in paired]
                item[field + "_baseline"] = statistics.mean(a) if a else None
                item[field + "_mean"] = statistics.mean(b) if b else None
                item[field + "_improvement_pct"] = (
                    100 * (sum(a) - sum(b)) / sum(a) if a and sum(a) else None
                )
            for label, cmp in [
                ("wins", lambda a, b: a < b),
                ("ties", lambda a, b: a == b),
                ("losses", lambda a, b: a > b),
            ]:
                item["flow_" + label] = sum(
                    cmp(r["mean_flow_time"], base["mean_flow_time"]) for base, r in paired
                )
            summaries.append(item)
    return summaries


def run_benchmark(output, seeds=10, solver_names=DEFAULT_SOLVERS, public_map=None):
    if type(seeds) is not int or not 1 <= seeds <= 30:
        raise ValueError("seeds must be 1..30")
    if (
        not solver_names
        or len(set(solver_names)) != len(solver_names)
        or "baseline" not in solver_names
        or set(solver_names) - set(SOLVERS)
    ):
        raise ValueError("Choose unique known solvers including baseline")
    sources = source_hashes()
    jobs = [
        (name, seed, partial(example, **config, seed=seed))
        for name, config in CONFIGS.items()
        for seed in range(seeds)
    ]
    if public_map:
        jobs.extend(
            (
                "movingai_heldout",
                seed,
                partial(derived_scene, public_map, "test", seed, task_count=16),
            )
            for seed in range(200, 206)
        )
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(
        root / "manifest.json",
        dict(
            status="running",
            configs=CONFIGS,
            seeds=list(range(seeds)),
            solvers=solver_names,
            public_map_sha256=hashlib.sha256(Path(public_map).read_bytes()).hexdigest()
            if public_map
            else None,
            public_test_seeds=list(range(200, 206)) if public_map else [],
            sources=sources,
            python=platform.python_version(),
            platform=platform.platform(),
            timing_repetitions=1,
            notes="Paired costs require both full task completion AND return. Public scores are derived MAPD, not official MAPF.",
        ),
    )
    rows = []
    # Flush every row, so an interrupted run has useful evidence and status=running.
    with (root / "runs.csv").open("x", encoding="utf-8-sig", newline="") as file:
        writer = None
        for name, seed, build in jobs:
            scene = build()
            digest = scenario_id(scene)
            for solver in solver_names:
                start = time.perf_counter()
                result = run_named(solver, scene)
                elapsed = time.perf_counter() - start
                validate(scene, result)
                routing = result.get("routing_stats", {})
                joint = result.get("joint_routing_stats", {})
                row = dict(
                    scenario=name,
                    seed=seed,
                    solver=solver,
                    sha256=digest,
                    feasible=result["feasible"],
                    completed=result["completed"],
                    total_tasks=result["total_tasks"],
                    runtime_seconds=elapsed,
                    accepted_replans=len(result["replanning_events"]),
                    replan_calls=result.get("algorithm", {}).get("replan_calls", 0),
                    expanded=routing.get("expanded", 0) + joint.get("expanded", 0),
                    generated=routing.get("generated", 0) + joint.get("generated", 0),
                    **{field: result[field] for field in FIELDS},
                )
                rows.append(row)
                if writer is None:
                    writer = csv.DictWriter(file, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                file.flush()
                # One representative trace per source family, not hundreds of duplicates.
                if seed in (0, 200) and solver in (
                    "baseline",
                    "joint_only",
                    "sipp_conflict",
                    "sipp_learned",
                ):
                    write_json(
                        root / "traces" / f"{name}-{solver}.json",
                        pack_scene(scene, {"algorithm": solver}, result),
                    )
            print(name, seed, "validated", flush=True)
    summary = summarize(rows)
    write_json(root / "summary.json", summary)
    with (root / "summary.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    if sources != source_hashes():
        raise RuntimeError("Source changed during benchmark; discard timing/summary and rerun")
    manifest = json.loads((root / "manifest.json").read_text())
    manifest.update(status="complete", validated_runs=len(rows))
    write_json(root / "manifest.json", manifest, overwrite=True)
    return rows, summary
