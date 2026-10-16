#!/usr/bin/env python3
"""Compare complete raw stream runs with indexed vs brute fallback conflicts.

Example (three rotated CPU measurements per backend and scene):
    .venv/bin/python scripts/benchmark_standby_index.py \
        --output runs/v91-index-performance.json

No scoring or validation is timed. The brute reference never constructs or
updates PlanReservations. Both implementations include stationary final tails
and reverse-edge conflicts. Full raw results, excluding genuine timer fields
only, must match before any timing comparison is accepted.
"""

import argparse
import hashlib
import json
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, process_time
from unittest.mock import patch

from agv.dispatch.registry import run_raw
from agv.evaluation.validation import validate
from agv.experiments.v91_bench import DEFAULT_WORKLOADS, build_scene, source_hashes
from agv.io.scenes import scenario_id
from agv.simulation import Environment

SIZES = ("medium", "large", "xlarge", "xxlarge")
WORKLOADS = ("sparse_uniform", "shared_bursts")
TIMER_FIELDS = {"cpu_seconds", "wall_seconds", "decision_cpu_seconds"}


class BruteReservations:
    """The prior full-future scan, reading peers from current suffixes only."""

    def __init__(self, environment):
        self.environment = environment

    def conflict(self, candidate, start, vehicle):
        env = self.environment
        if start != env.time:
            raise ValueError("Brute full-suffix reference requires the current absolute time")
        horizon = max([len(candidate)] + [len(path) for path in env._plans])
        for offset in range(horizon):
            point = candidate[min(offset, len(candidate) - 1)]
            for peer, path in enumerate(env._plans):
                if peer == vehicle:
                    continue
                other = path[min(offset, len(path) - 1)]
                if point == other:
                    return "vertex"
                if offset:
                    previous = candidate[min(offset - 1, len(candidate) - 1)]
                    other_previous = path[min(offset - 1, len(path) - 1)]
                    if point == other_previous and previous == other:
                        return "edge"
        return None


def _brute_view(environment):
    if environment._reservation_index is not None:
        raise AssertionError("Brute reference unexpectedly constructed a reservation index")
    return BruteReservations(environment)


def _without_timers(value):
    if isinstance(value, dict):
        return {
            key: _without_timers(item) for key, item in value.items() if key not in TIMER_FIELDS
        }
    if isinstance(value, (tuple, list)):
        return [_without_timers(item) for item in value]
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _timed(scene, backend):
    if backend == "brute":
        with patch.object(Environment, "plan_reservations", _brute_view):
            cpu, wall = process_time(), perf_counter()
            result = run_raw("sipp_stream_dispatch", scene)
            cpu, wall = process_time() - cpu, perf_counter() - wall
    elif backend == "indexed":
        cpu, wall = process_time(), perf_counter()
        result = run_raw("sipp_stream_dispatch", scene)
        cpu, wall = process_time() - cpu, perf_counter() - wall
    else:
        raise ValueError("Unknown reservation implementation")
    # All source checks, result comparisons and independent trajectory audits
    # occur outside the raw execution timer, including the actual baseline.
    if not result["feasible"] or not validate(scene, result):
        raise AssertionError("Performance comparison requires a complete independently valid run")
    return result, dict(cpu_seconds=cpu, wall_seconds=wall)


def benchmark(*, repeats=3, seed=10, sizes=SIZES, workloads=WORKLOADS):
    if type(repeats) is not int or repeats < 3:
        raise ValueError("At least three measurements per backend and scene are required")
    frozen = source_hashes()
    report = dict(
        schema="agv-standby-index-performance-v1",
        created_at=datetime.now(timezone.utc).isoformat(),
        python=platform.python_version(),
        platform=platform.platform(),
        solver="sipp_stream_dispatch",
        seed=seed,
        repeats_per_backend=repeats,
        source_hashes=frozen,
        timed_scope="Entire raw run, including index construction and every update; no scoring/validation",
        equality_scope="Full raw result after recursively removing only listed real timer fields",
        ignored_timer_fields=sorted(TIMER_FIELDS),
        data_origin="Synthetic V9.1 templates; 4 vehicles and 12 jobs; development seed",
        limitation="Local descriptive CPU measurements, not a general machine-performance guarantee",
        scenes=[],
    )
    for size in sizes:
        for workload in workloads:
            if size not in SIZES or workload not in WORKLOADS:
                raise ValueError("Unknown benchmark template")
            options = {"size": size, "vehicles": 4}
            scene = build_scene(options, DEFAULT_WORKLOADS[workload], seed)
            row = dict(
                size=size,
                workload=workload,
                scenario_sha256=scenario_id(scene),
                generator={**options, **DEFAULT_WORKLOADS[workload], "seed": seed},
                task_count=len(scene.tasks),
                vehicle_count=len(scene.homes),
                order_stream_end=scene.order_stream_end,
                samples=[],
            )
            last_digest = None
            for repetition in range(repeats):
                order = ("indexed", "brute")
                if (len(report["scenes"]) + repetition) % 2:
                    order = order[::-1]
                results, timings = {}, {}
                for backend in order:
                    if source_hashes() != frozen:
                        raise RuntimeError(
                            "Source changed during reservation performance experiment"
                        )
                    raw, timings[backend] = _timed(scene, backend)
                    results[backend] = _without_timers(raw)
                    if source_hashes() != frozen:
                        raise RuntimeError(
                            "Source changed during reservation performance experiment"
                        )
                if results["indexed"] != results["brute"]:
                    raise AssertionError(f"Full raw results differ: {size}/{workload}/{repetition}")
                digest = _digest(results["indexed"])
                if last_digest is not None and digest != last_digest:
                    raise AssertionError(
                        "Repeated deterministic raw execution changed quality or trajectory"
                    )
                last_digest = digest
                row["samples"].append(
                    dict(
                        repetition=repetition,
                        execution_order=order,
                        timings=timings,
                        full_results_equal=True,
                        sanitized_result_sha256=digest,
                    )
                )
            medians = {
                backend: statistics.median(
                    sample["timings"][backend]["cpu_seconds"] for sample in row["samples"]
                )
                for backend in ("indexed", "brute")
            }
            row.update(
                median_cpu_seconds=medians,
                indexed_over_brute_cpu=medians["indexed"] / medians["brute"],
                brute_over_indexed_speedup=medians["brute"] / medians["indexed"],
                complete=True,
                independently_valid=True,
            )
            report["scenes"].append(row)
            print(
                f"{size}/{workload}: indexed={medians['indexed']:.6f}s "
                f"brute={medians['brute']:.6f}s "
                f"indexed/brute={row['indexed_over_brute_cpu']:.4f}",
                flush=True,
            )
    report["complete"] = True
    report["raw_runs"] = len(report["scenes"]) * repeats * 2
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/v91-index-performance.json"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=10)
    parser.add_argument("--sizes", nargs="+", choices=SIZES, default=SIZES)
    parser.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=WORKLOADS)
    args = parser.parse_args()
    report = benchmark(
        repeats=args.repeats, seed=args.seed, sizes=args.sizes, workloads=args.workloads
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
