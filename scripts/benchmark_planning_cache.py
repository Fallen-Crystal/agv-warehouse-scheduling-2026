#!/usr/bin/env python3
"""Compare exact ETA and warm shared-distance caches without timing validation.

    .venv/bin/python scripts/benchmark_planning_cache.py \
        --output results/architecture-options-2026/planning-cache-benchmark.json

Static sharing compares the same BFS implementation with its cross-instance
LRU enabled/disabled. A separate untimed run primes the shared cache. This is
same-process warm reuse, not a first-run or cross-machine performance claim.
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, process_time
from unittest.mock import patch

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.v91_bench import DEFAULT_WORKLOADS, build_scene, source_hashes
from agv.io.scenes import scenario_id
from agv.io.storage import write_json
from agv.planning.distance import _distances
from agv.registry import SOLVERS
from agv.runner import run

ROOT = Path(__file__).resolve().parents[1]
CACHE_FIELDS = frozenset(("decision_routing_stats", "eta_cache_stats"))


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _execute(scene, spec, shared):
    distance_function = _distances if shared else _distances.__wrapped__
    with patch("agv.planning.distance._distances", distance_function):
        cpu, wall = process_time(), perf_counter()
        raw = run(spec, scene)
        cpu, wall = process_time() - cpu, perf_counter() - wall
    if not raw["feasible"] or not validate(scene, raw):
        raise ValueError("Only complete independently validated runs are comparable")
    scored = score_result(scene, raw)
    if not validate(scene, scored):
        raise ValueError("Independent scored-result validation failed")
    measurement = dict(
        cpu_seconds=cpu,
        wall_seconds=wall,
        execution_route_calls=raw["routing_stats"]["calls"],
        decision_route_calls=raw["decision_routing_stats"]["calls"],
        total_route_calls=raw["routing_stats"]["calls"] + raw["decision_routing_stats"]["calls"],
        eta_cache=raw.get("eta_cache_stats"),
    )
    return raw, scored, measurement


def _case(scene, solver, mechanism, repeats, offset):
    base = SOLVERS[solver]
    specs = {
        "off": base,
        "on": replace(base, assign=replace(base.assign, eta_cache_capacity=256))
        if mechanism == "eta"
        else base,
    }
    _distances.cache_clear()
    _execute(scene, base, True)  # Untimed priming includes the same audit/reference work.
    samples = {"off": [], "on": []}
    expected, expected_score = None, None
    for repeat in range(repeats):
        order = ("off", "on") if (repeat + offset) % 2 == 0 else ("on", "off")
        for label in order:
            shared = mechanism == "eta" or label == "on"
            raw, scored, sample = _execute(scene, specs[label], shared)
            comparable = (
                {key: value for key, value in raw.items() if key not in CACHE_FIELDS}
                if mechanism == "eta"
                else raw
            )
            if expected is None:
                expected, expected_score = comparable, scored["weighted_score"]
            if comparable != expected or scored["weighted_score"] != expected_score:
                raise ValueError(f"Complete execution differs: {mechanism}/{solver}/{label}")
            sample.update(repeat=repeat, order=list(order), measurement_position=order.index(label))
            samples[label].append(sample)
    medians = {
        label: statistics.median(sample["cpu_seconds"] for sample in values)
        for label, values in samples.items()
    }
    off_calls = samples["off"][0]["decision_route_calls"]
    on_calls = samples["on"][0]["decision_route_calls"]
    reduction = 1 - on_calls / off_calls if off_calls else 0
    total_off, total_on = (samples[label][0]["total_route_calls"] for label in ("off", "on"))
    total_reduction = 1 - total_on / total_off if total_off else 0
    return dict(
        solver=solver,
        mechanism=mechanism,
        scenario_sha256=scenario_id(scene),
        vehicles=len(scene.homes),
        jobs=len(scene.tasks),
        repetitions_per_backend=repeats,
        samples=samples,
        cpu_medians=medians,
        cpu_speedup=medians["off"] / medians["on"],
        decision_route_call_reduction=reduction,
        total_route_call_reduction=total_reduction,
        requested_call_reduction=0.4 if mechanism == "eta" else None,
        requested_call_reduction_metric="total_route_calls" if mechanism == "eta" else None,
        requested_call_reduction_met=total_reduction >= 0.4 if mechanism == "eta" else None,
        independently_audited_executions=2 * repeats,
        full_raw_equal_after_listed_diagnostics=True,
        ignored_diagnostic_fields=sorted(CACHE_FIELDS) if mechanism == "eta" else [],
        full_compared_result_sha256=_digest(expected),
        full_paths_sha256=_digest(expected["paths"]),
        full_assignments_sha256=_digest(expected["assignments"]),
        F_equal=True,
        F=expected_score,
        warmup="One separate untimed run with static sharing enabled",
    )


def benchmark(*, repeats=3, seed=10):
    if type(repeats) is not int or repeats < 3:
        raise ValueError("At least three repetitions per backend are required")
    frozen = source_hashes()
    rows = []
    for workload, options in DEFAULT_WORKLOADS.items():
        scene = build_scene({"size": "medium", "vehicles": 4}, options, seed)
        for mechanism, solvers in (
            ("eta", ("sipp_stream_matching", "sipp_position_delay_dispatch")),
            ("static_distance", ("sipp_position_delay_dispatch",)),
        ):
            for solver in solvers:
                row = _case(scene, solver, mechanism, repeats, len(rows))
                row.update(workload=workload, seed=seed, map="medium")
                rows.append(row)
                if source_hashes() != frozen:
                    raise ValueError("Source changed during planning-cache measurement")
                print(
                    f"{workload}/{mechanism}/{solver}: validated, "
                    f"CPU {row['cpu_speedup']:.3f}x, "
                    f"decision calls {row['decision_route_call_reduction']:.1%} fewer",
                    flush=True,
                )
    return dict(
        schema="agv-planning-cache-performance-v1",
        status="verified",
        created_at=datetime.now(timezone.utc).isoformat(),
        environment=dict(
            python=platform.python_version(),
            implementation=platform.python_implementation(),
            platform=platform.platform(),
            machine=platform.machine(),
            processor=platform.processor(),
            logical_cpus=os.cpu_count(),
            workers=1,
        ),
        source_hashes=frozen,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        seed=seed,
        timed_scope="Entire raw runner execution; validation, scoring and reference excluded",
        data_origin="Synthetic medium V9.1 map, four vehicles, twelve jobs, three workloads",
        comparison="Same scene/spec except the named cache; order rotates between repetitions",
        limitation="Descriptive same-process warm static-cache reuse on one seed/template; background machine load, including concurrent development experiments, is uncontrolled. No cold-start, cross-machine or unseen-scene speed guarantee. A failed 40% ETA call target is reported, not hidden.",
        rows=rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=10)
    args = parser.parse_args()
    report = benchmark(repeats=args.repeats, seed=args.seed)
    report["command"] = (
        f".venv/bin/python scripts/benchmark_planning_cache.py --output {args.output} "
        f"--repeats {args.repeats} --seed {args.seed}"
    )
    write_json(args.output, report)


if __name__ == "__main__":
    main()
