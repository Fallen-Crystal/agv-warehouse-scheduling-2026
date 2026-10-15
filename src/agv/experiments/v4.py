"""Paired V4 experiments; references are prepared offline before solver timing."""

import csv
import platform
import statistics
import time
from pathlib import Path

from agv.dispatch.registry import run_named
from agv.evaluation.objective import reference_context
from agv.evaluation.validation import validate
from agv.experiments.batch import aggregate
from agv.experiments.benchmark import source_hashes
from agv.io.scenes import pack_scene, scenario_id
from agv.io.storage import write_json
from agv.warehouse.layout import generate

CONFIGS = {
    "static_layers": dict(task_count=18, vehicles=4),
    "dynamic_equipment": dict(
        mode="dynamic",
        arrival="burst",
        task_count=24,
        vehicles=6,
        obstacle_layout="columns_equipment",
    ),
    "dynamic_shared": dict(
        mode="dynamic", arrival="irregular", task_count=24, vehicles=6, delivery_pattern="shared"
    ),
}
SOLVERS = ("baseline", "sipp_budget", "sipp_matching")
FIELDS = (
    "feasible",
    "completed",
    "total_tasks",
    "completion_rate",
    "makespan",
    "time",
    "mean_flow_time",
    "p90_flow_time",
    "moves",
    "empty_moves",
    "loaded_moves",
    "traffic_wait_steps",
    "score_valid",
    "weighted_score",
    "normalized_time",
    "normalized_response",
    "normalized_distance",
)


def run_web_batch(config, seeds, solver):
    from agv.web.app import build_scene

    rows, entries = [], []
    for seed in seeds:
        options = {**config, "seed": seed}
        scene = build_scene(options)
        reference_context(scene)
        started = time.perf_counter()
        result = run_named(solver, scene)
        elapsed = time.perf_counter() - started
        validate(scene, result)
        rows.append(
            dict(
                policy=solver,
                seed=seed,
                scenario_sha256=scenario_id(scene),
                runtime_seconds=elapsed,
                max_flow_time=result["max_flow_time"],
                **{k: result[k] for k in FIELDS},
            )
        )
        entries.append(
            dict(
                config=options,
                scenario=scene.to_dict(),
                result=result,
                scenario_sha256=scenario_id(scene),
                policy=solver,
            )
        )
    summaries = aggregate(rows)
    valid = [r["weighted_score"] for r in rows if r["score_valid"]]
    summaries[0].update(
        weighted_score_mean=statistics.mean(valid) if valid else None, score_samples=len(valid)
    )
    return dict(config=config, seeds=list(seeds), rows=rows, summaries=summaries, entries=entries)


def run_benchmark(output, seeds=6):
    if type(seeds) is not int or not 1 <= seeds <= 20:
        raise ValueError("seeds must be 1..20")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    sources = source_hashes()
    manifest = dict(
        status="running",
        configs=CONFIGS,
        solvers=SOLVERS,
        seeds=list(range(seeds)),
        source_hashes=sources,
        python=platform.python_version(),
        platform=platform.platform(),
        timing_repetitions=1,
        notes="Finite task completion, not steady-state throughput. Offline fixed reference is computed before solver timing. Timed solver includes cached score audit; final validation is outside timing. Full success required for costs.",
    )
    write_json(root / "manifest.json", manifest)
    rows = []
    with (root / "runs.csv").open("x", encoding="utf-8-sig", newline="") as file:
        writer = None
        for name, config in CONFIGS.items():
            for seed in range(seeds):
                scene = generate(**config, seed=seed)
                digest = scenario_id(scene)
                reference_context(scene)
                order = list(SOLVERS)
                order = order[seed % len(order) :] + order[: seed % len(order)]
                for solver in order:
                    started = time.perf_counter()
                    result = run_named(solver, scene)
                    elapsed = time.perf_counter() - started
                    validate(scene, result)
                    assert scenario_id(scene) == digest
                    row = dict(
                        scenario=name,
                        seed=seed,
                        solver=solver,
                        scenario_sha256=digest,
                        runtime_seconds=elapsed,
                        replan_calls=result.get("algorithm", {}).get("replan_calls", 0),
                        accepted_replans=len(result["replanning_events"]),
                        **{k: result[k] for k in FIELDS},
                    )
                    rows.append(row)
                    if writer is None:
                        writer = csv.DictWriter(file, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    file.flush()
                    if seed == 0 and solver in ("baseline", "sipp_budget"):
                        write_json(
                            root / "traces" / f"{name}-{solver}.json",
                            pack_scene(scene, {"algorithm": solver}, result),
                        )
                print(name, seed, "validated", flush=True)
    summaries = []
    for name in CONFIGS:
        baseline = {
            r["seed"]: r for r in rows if r["scenario"] == name and r["solver"] == "baseline"
        }
        for solver in SOLVERS:
            own = [r for r in rows if r["scenario"] == name and r["solver"] == solver]
            good = [
                r
                for r in own
                if r["feasible"] and r["score_valid"] and baseline[r["seed"]]["feasible"]
            ]
            item = dict(
                scenario=name,
                solver=solver,
                runs=len(own),
                successes=sum(r["feasible"] for r in own),
                paired_successes=len(good),
                runtime_mean=statistics.mean(r["runtime_seconds"] for r in own),
            )
            for field in ("makespan", "mean_flow_time", "p90_flow_time", "moves", "weighted_score"):
                a, b = [baseline[r["seed"]][field] for r in good], [r[field] for r in good]
                item[field + "_mean"] = statistics.mean(b) if b else None
                item[field + "_improvement_pct"] = (
                    100 * (sum(a) - sum(b)) / sum(a) if a and sum(a) else None
                )
            item["score_wins"] = sum(
                r["weighted_score"] < baseline[r["seed"]]["weighted_score"] for r in good
            )
            summaries.append(item)
    if source_hashes() != sources:
        raise RuntimeError("Source changed during V4 benchmark")
    write_json(root / "summary.json", summaries)
    manifest.update(
        status="complete",
        validated_runs=len(rows),
        successful_runs=sum(r["feasible"] for r in rows),
    )
    write_json(root / "manifest.json", manifest, overwrite=True)
    return rows, summaries
