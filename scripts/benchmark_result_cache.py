#!/usr/bin/env python3
"""Measure a cold/warm V9.1 matrix without bypassing independent validation."""

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

from agv.experiments.v91_bench import default_protocol, read_rows
from agv.io.storage import write_json

ROOT = Path(__file__).resolve().parents[1]
CLOCK_FIELDS = {
    "cpu_seconds",
    "wall_seconds",
    "cache_status",
    "timing_origin",
    "measurement_environment",
}


def _compare(first, second):
    rows = [read_rows(root / "runs.csv") for root in (first, second)]
    normalized = [
        [{key: value for key, value in row.items() if key not in CLOCK_FIELDS} for row in items]
        for items in rows
    ]
    if normalized[0] != normalized[1] or not all(
        row["comparison_valid"] for items in rows for row in items
    ):
        raise ValueError("Non-timing rows differ or contain failed executions")
    traces = list((first / "traces").glob("*.json"))
    if not traces or any(
        path.read_bytes() != (second / "traces" / path.name).read_bytes() for path in traces
    ):
        raise ValueError("Representative trajectories differ")
    return dict(
        runs_per_pass=len(rows[0]),
        non_timing_rows_equal=True,
        representative_traces_byte_equal=len(traces),
    )


def benchmark(output, *, workers=2, evidence=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    protocol = default_protocol()
    protocol.update(
        seeds=[10, 11],
        maps={key: protocol["maps"][key] for key in ("medium", "large")},
        solvers={key: protocol["solvers"][key] for key in ("G0", "G4", "B0", "B1")},
        bootstrap={"resamples": 100, "seed": 20261020},
    )
    smoke = default_protocol()
    smoke.update(
        seeds=[10, 11],
        maps={"medium": {"size": "medium", "vehicles": 1}},
        workloads={"dense_static": {"mode": "static", "task_count": 2}},
        solvers={"G0": "sipp_stream_dispatch", "G1": "sipp_stream_matching"},
        bootstrap={"resamples": 100, "seed": 20261020},
    )
    write_json(output / "protocol.json", protocol)
    write_json(output / "smoke-protocol.json", smoke)
    durations = {}
    for label, config, count, cached in (
        ("serial", "smoke-protocol.json", 1, False),
        ("parallel", "smoke-protocol.json", workers, False),
        ("cold", "protocol.json", workers, True),
        ("warm", "protocol.json", workers, True),
    ):
        command = [
            sys.executable,
            "-m",
            "agv",
            "benchmark-v91",
            "--protocol",
            str(output / config),
            "--output",
            str(output / label),
            "--workers",
            str(count),
        ]
        command += ["--cache-dir", str(output / "cache")] if cached else ["--no-cache"]
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        durations[label] = time.perf_counter() - started
        (output / (label + ".stdout.txt")).write_text(completed.stdout, encoding="utf-8")
        (output / (label + ".stderr.txt")).write_text(completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"{label} failed; retained logs and manifest at {output}")
    serial_parallel = _compare(output / "serial", output / "parallel")
    cold_warm = _compare(output / "cold", output / "warm")
    manifests = {
        label: json.loads((output / label / "manifest.json").read_text(encoding="utf-8"))
        for label in durations
    }
    sources = manifests["cold"]["source_hashes"]
    if any(manifest["source_hashes"] != sources for manifest in manifests.values()):
        raise ValueError("Measured passes do not share one source snapshot")
    spec = importlib.util.spec_from_file_location(
        "verify_v91_cache", ROOT / "scripts/verify_v91.py"
    )
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    audits = {label: verifier.verify(output / label) for label in durations}
    cold_rows, warm_rows = [read_rows(output / label / "runs.csv") for label in ("cold", "warm")]
    if any(row["cache_status"] != "miss" for row in cold_rows) or any(
        row["cache_status"] != "hit" for row in warm_rows
    ):
        raise ValueError("Expected a cold cache followed by a complete warm hit")
    ratio = durations["warm"] / durations["cold"]
    report = dict(
        schema="agv-batch-cache-benchmark-v1",
        status="verified",
        output=str(output.resolve()),
        command=f"{sys.executable} scripts/benchmark_result_cache.py --output {output} --workers {workers}",
        protocol=protocol,
        source_hashes=sources,
        workers=workers,
        wall_seconds=durations,
        serial_parallel=serial_parallel,
        cold_warm=cold_warm,
        hits=len(warm_rows),
        hit_rate=1.0,
        warm_cold_ratio=ratio,
        speedup=1 / ratio,
        within_five_percent=ratio <= 0.05,
        audits=audits,
        timing_note="Separate CLI processes; total elapsed retains independent validation, reference reproduction, source checks, bootstrap and IO. Cached CPU/wall values are original measurements. Background machine load is uncontrolled; this measures experiment reuse, not algorithm speed.",
    )
    write_json(output / "performance.json", report)
    if evidence is not None:
        write_json(evidence, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            benchmark(args.output, workers=args.workers, evidence=args.evidence),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
