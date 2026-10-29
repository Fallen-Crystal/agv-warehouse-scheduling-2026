"""Frozen opt-in architecture experiments, separate from the historical V9.1 holdout.

Development uses seeds 10--19. Freeze the chosen configuration before running
30--49; full paired metrics and independent validation failures remain in JSON.
"""

import argparse
import json
import statistics
import time
from dataclasses import asdict, replace
from pathlib import Path

from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.experiments.cache import canonical
from agv.experiments.v91_bench import DEFAULT_WORKLOADS, _interval, build_scene, source_hashes
from agv.io.scenes import scenario_id
from agv.io.storage import write_json
from agv.registry import SOLVERS
from agv.runner import run
from agv.runner.batch import BatchTask, run_batch

SCHEMA = "agv-architecture-options-v1"
RANGES = {"development": (10, 19), "holdout": (30, 49)}
METRICS = (
    "weighted_score",
    "makespan",
    "mean_flow_time",
    "moves",
    "p90_flow_time",
    "empty_moves",
    "traffic_wait_steps",
    "cpu_seconds",
)
DEFAULT_CONFIG = {
    "maps": {"medium": {"size": "medium", "vehicles": 4}},
    "workloads": DEFAULT_WORKLOADS,
    "baseline": "baseline",
    "solvers": {
        "baseline": {"base": "sipp_stream_dispatch"},
        "positioning": {"base": "sipp_position_delay_dispatch"},
        "window": {
            "base": "sipp_position_delay_dispatch",
            "idle": {"stat_window": 100, "rebalance_period": 500},
        },
        "hotspot": {
            "base": "sipp_position_delay_dispatch",
            "idle": {"stat_window": 100, "rebalance_period": 500, "hotspot_zones": 1},
        },
    },
}


def build_specs(config):
    if not isinstance(config, dict) or set(config) != {"maps", "workloads", "baseline", "solvers"}:
        raise ValueError("Config needs maps, workloads, baseline and solvers")
    if not all(
        isinstance(config[key], dict) and config[key] for key in ("maps", "workloads", "solvers")
    ):
        raise ValueError("Experiment dimensions must be nonempty objects")
    if config["baseline"] not in config["solvers"]:
        raise ValueError("Baseline must be among solvers")
    specs = {}
    for name, options in config["solvers"].items():
        if not isinstance(options, dict) or set(options) - {"base", "idle", "assign"}:
            raise ValueError("Solver options only support base, idle and assign")
        if options.get("base") not in SOLVERS:
            raise ValueError("Solver base must be a registered name")
        spec = SOLVERS[options["base"]]
        specs[name] = replace(
            spec,
            idle=replace(spec.idle, **options.get("idle", {})),
            assign=replace(spec.assign, **options.get("assign", {})),
        )
    return specs


def freeze(config, path):
    """Freeze a selected configuration and all shipped source before holdout."""
    specs = build_specs(config)
    manifest = dict(
        schema=SCHEMA,
        config=json.loads(canonical(config)),
        solver_specs={name: json.loads(canonical(asdict(spec))) for name, spec in specs.items()},
        source_hashes=source_hashes(),
        holdout_seeds=list(range(30, 50)),
    )
    write_json(path, manifest)
    return manifest


def check_protocol(config, split, seeds, frozen, sources):
    if split not in RANGES:
        raise ValueError("Unknown experiment split")
    low, high = RANGES[split]
    if (
        not seeds
        or len(seeds) != len(set(seeds))
        or any(type(seed) is not int or not low <= seed <= high for seed in seeds)
    ):
        raise ValueError(f"{split} seeds must be unique integers in {low}..{high}")
    if split == "holdout" and (
        not isinstance(frozen, dict)
        or frozen.get("schema") != SCHEMA
        or canonical(frozen.get("config")) != canonical(config)
        or frozen.get("source_hashes") != sources
        or any(seed not in frozen.get("holdout_seeds", []) for seed in seeds)
    ):
        raise ValueError("Holdout requires the unchanged frozen configuration and source")


def _execute(payload):
    map_name, map_options, workload, workload_options, seed, solver_options = payload
    scene = build_scene(map_options, workload_options, seed)
    context = reference_context(scene)
    specs = build_specs(solver_options)
    names = list(specs)
    rotate = seed % len(names)
    rows = []
    for name in names[rotate:] + names[:rotate]:
        started_cpu, started_wall = time.process_time(), time.perf_counter()
        result, failure_stage, audit_error = {}, None, None
        try:
            result = run(specs[name], scene)
            if not isinstance(result, dict):
                raise TypeError("Raw solver must return a result mapping")
        except Exception as error:
            result = result if isinstance(result, dict) else {}
            failure_stage, audit_error = "execution", f"{type(error).__name__}: {error}"
        cpu, wall = time.process_time() - started_cpu, time.perf_counter() - started_wall
        scored = result
        if failure_stage is None:
            try:
                validate(scene, result)
            except Exception as error:
                failure_stage, audit_error = "validation", f"{type(error).__name__}: {error}"
        if failure_stage is None:
            try:
                scored = score_result(scene, result, reference=context)
            except Exception as error:
                failure_stage, audit_error = "scoring", f"{type(error).__name__}: {error}"
        rows.append(
            dict(
                map=map_name,
                workload=workload,
                seed=seed,
                solver=name,
                scenario_sha256=scenario_id(scene),
                valid=failure_stage is None
                and result.get("feasible", False)
                and scored.get("score_valid", False),
                failure_stage=failure_stage,
                audit_error=audit_error,
                **{key: scored.get(key) for key in METRICS if key != "cpu_seconds"},
                cpu_seconds=cpu,
                wall_seconds=wall,
            )
        )
    return rows


def summarize(rows, baseline):
    identities = {(r["map"], r["workload"], r["seed"], r["solver"]) for r in rows}
    if len(identities) != len(rows):
        raise ValueError("Duplicate experiment rows")
    paired = {(r["map"], r["workload"], r["seed"]): r for r in rows if r["solver"] == baseline}
    for row in rows:
        control = paired.get((row["map"], row["workload"], row["seed"]))
        if control is None or control["scenario_sha256"] != row["scenario_sha256"]:
            raise ValueError("Missing or mismatched paired input")
    output = {}
    for solver in dict.fromkeys(r["solver"] for r in rows):
        if solver == baseline:
            continue
        for group in ("all", *dict.fromkeys(r["workload"] for r in rows)):
            pairs = [
                (r, paired[(r["map"], r["workload"], r["seed"])])
                for r in rows
                if r["solver"] == solver and (group == "all" or r["workload"] == group)
            ]
            good = [(r, b) for r, b in pairs if r["valid"] and b["valid"]]
            gains = [
                100 * (b["weighted_score"] - r["weighted_score"]) / b["weighted_score"]
                for r, b in good
                if b["weighted_score"] > 0
            ]
            output[f"{solver}/{group}"] = dict(
                pairs=len(pairs),
                valid_pairs=len(good),
                scored_pairs=len(gains),
                mean_F_gain_pct=statistics.mean(gains) if gains else None,
                paired_F_ci95=_interval(gains, {"seed": 20261020, "resamples": 2000}),
                p90_worse=sum(r["p90_flow_time"] > b["p90_flow_time"] for r, b in good),
                mean_deltas={
                    key: statistics.mean(r[key] - b[key] for r, b in good) if good else None
                    for key in METRICS
                },
                mean_cpu_ratio=statistics.mean(r["cpu_seconds"] / b["cpu_seconds"] for r, b in good)
                if good
                else None,
            )
    return output


def benchmark(output, config=None, *, split="development", seeds=None, frozen=None, workers=1):
    destination = Path(output)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    config = DEFAULT_CONFIG if config is None else config
    if split not in RANGES:
        raise ValueError("Unknown experiment split")
    build_specs(config)
    sources = source_hashes()
    seeds = list(range(RANGES[split][0], RANGES[split][1] + 1)) if seeds is None else list(seeds)
    check_protocol(config, split, seeds, frozen, sources)
    tasks = [
        BatchTask(seed, (m, mo, w, wo, seed, config))
        for m, mo in config["maps"].items()
        for w, wo in config["workloads"].items()
        for seed in seeds
    ]
    rows = [row for result in run_batch(tasks, _execute, workers=workers) for row in result]
    if source_hashes() != sources:
        raise RuntimeError("Source changed during experiment; freeze and rerun")
    report = dict(
        schema=SCHEMA,
        split=split,
        seeds=seeds,
        config=config,
        source_hashes=sources,
        solver_specs={
            name: json.loads(canonical(asdict(spec))) for name, spec in build_specs(config).items()
        },
        inference="Fixed synthetic templates; paired seeds, not unseen-map or optimality evidence",
        rows=rows,
        summary=summarize(rows, config["baseline"]),
    )
    write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--split", choices=RANGES, default="development")
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else DEFAULT_CONFIG
    if args.freeze:
        freeze(config, args.output)
        return
    frozen = json.loads(args.frozen.read_text(encoding="utf-8")) if args.frozen else None
    report = benchmark(
        args.output, config, split=args.split, seeds=args.seeds, frozen=frozen, workers=args.workers
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
