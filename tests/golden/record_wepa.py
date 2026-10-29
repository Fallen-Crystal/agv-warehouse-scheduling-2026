"""Record deterministic WEPA traces through the audited runtime's own entry point.

Full trajectories belong in an ignored runs directory. Only the compact fixture is
intended for Git. Each replay uses a fresh process and a real wall-clock timeout.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CASES = (
    "wepa-day12-bin1164",
    "wepa-day32-bin3113",
    "wepa-day33-bin3229",
    "wepa-day45-bin4335",
)
METRICS = (
    "valid",
    "T",
    "R",
    "D",
    "F",
    "J",
    "tasks",
    "p90",
    "empty_distance",
    "traffic_wait",
    "objective_sha256",
)


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical(trace):
    """Exclude only machine clocks and implementation/output-location identity."""
    return {
        "case": trace["case"],
        "row": {key: value for key, value in trace["row"].items() if key not in ("cpu", "wall")},
        "result": trace["result"],
        "scoring": trace["scoring"],
    }


def summarize(trace):
    result = trace["result"]
    for key in ("paths", "labels", "records", "decisions", "completed", "final_stock"):
        assert key in result, f"Missing semantic trace field: {key}"
    assert trace["row"]["valid"] and trace["scoring"]["audit"]["valid"]
    assert len(result["records"]) == trace["row"]["tasks"]
    assert len(result["completed"]) == trace["row"]["tasks"]
    assert result["D"] == sum(a != b for p in result["paths"] for a, b in zip(p, p[1:]))
    return {
        **{key: trace["row"][key] for key in METRICS},
        "canonical_sha256": digest(canonical(trace)),
        "input_sha256": digest(trace["case"]),
        "paths_sha256": digest(result["paths"]),
        "labels_sha256": digest(result["labels"]),
        "assignments_sha256": digest(result["decisions"]),
        "service_events_sha256": digest(result["records"]),
        "final_stock_sha256": digest(result["final_stock"]),
        "audit": trace["scoring"]["audit"],
    }


def self_check():
    trace = {
        "case": {"id": 1},
        "row": {"T": 3, "cpu": 1, "wall": 2},
        "result": {"records": [{"end": 3}]},
        "scoring": {"F": 4},
        "implementation_sha256": "old",
        "config": {"output": "old"},
    }
    changed = json.loads(json.dumps(trace))
    changed["row"].update(cpu=5, wall=6)
    changed["config"]["output"] = "new"
    changed["implementation_sha256"] = "new"
    assert canonical(trace) == canonical(changed)
    changed["result"]["records"][0]["end"] = 4
    assert digest(canonical(trace)) != digest(canonical(changed))


def worker(args):
    if args.backend_root:
        sys.path.insert(0, str(Path(args.backend_root).resolve()))
    sys.argv = [
        args.module,
        "--case",
        args.case,
        "--profile",
        args.profile,
        "--seed",
        str(args.seed),
        "--output",
        args.output,
    ]
    importlib.import_module(args.module).main()


def execute(args, case, profile, repeat, output):
    name = f"{case}-{profile}-s{args.seed}-r{repeat}"
    raw_path, log_path = output / f"{name}.json", output / f"{name}.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--module",
        args.module,
        "--case",
        case,
        "--profile",
        profile,
        "--seed",
        str(args.seed),
        "--output",
        str(raw_path),
    ]
    if args.backend_root:
        command.extend(("--backend-root", str(Path(args.backend_root).resolve())))
    started = time.perf_counter()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        with log_path.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=os.name == "posix",
            )
            try:
                process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                raise
        if process.returncode:
            raise ValueError(f"Backend exited {process.returncode}; see {log_path}")
        trace = json.loads(raw_path.read_text(encoding="utf-8"))
        row = dict(
            case=case,
            profile=profile,
            seed=args.seed,
            repeat=repeat,
            status="passed",
            elapsed_wall=time.perf_counter() - started,
            raw=raw_path.name,
            log=log_path.name,
            measured_cpu=trace["row"]["cpu"],
            measured_wall=trace["row"]["wall"],
            summary=summarize(trace),
        )
    except (OSError, ValueError, AssertionError, subprocess.TimeoutExpired) as error:
        row = dict(
            case=case,
            profile=profile,
            seed=args.seed,
            repeat=repeat,
            status="failed",
            elapsed_wall=time.perf_counter() - started,
            raw=raw_path.name,
            log=log_path.name,
            error=str(error),
        )
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-root", help="Original archive root; omit for an installed package"
    )
    parser.add_argument("--module", default="run_main", help="Module exposing the existing main()")
    parser.add_argument("--profiles", default="gate,hungarian,hga")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--expect", type=Path, help="Compare against a previous compact fixture")
    parser.add_argument("--archive", type=Path, help="Retain original ZIP SHA-256 provenance")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    args = parser.parse_args()
    self_check()
    if args.worker:
        return worker(args)
    if args.out is None or args.repeats < 2 or args.timeout <= 0:
        parser.error("--out, --repeats >= 2, and --timeout > 0 are required")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixture_path = (args.fixture or output / "fixture.json").resolve()
    if fixture_path.exists():
        raise ValueError(f"Refuse to overwrite fixture: {fixture_path}")
    cases, profiles = args.cases.split(","), args.profiles.split(",")
    assert len(set(cases)) == len(cases) and len(set(profiles)) == len(profiles)
    tasks = [
        (case, profile, repeat)
        for case in cases
        for profile in profiles
        for repeat in range(args.repeats)
    ]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(execute, args, *task, output) for task in tasks]
        rows = [future.result() for future in futures]
    (output / "runs.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fixtures, problems = {}, []
    for case in cases:
        for profile in profiles:
            key = f"{case}/{profile}/s{args.seed}"
            matching = [row for row in rows if row["case"] == case and row["profile"] == profile]
            if any(row["status"] != "passed" for row in matching):
                problems.append(f"{key}: execution or audit failure")
                continue
            summaries = [row["summary"] for row in matching]
            if any(summary != summaries[0] for summary in summaries[1:]):
                problems.append(f"{key}: full semantic replay is not deterministic")
                continue
            fixtures[key] = summaries[0]
    if args.expect:
        expected = json.loads(args.expect.read_text(encoding="utf-8"))["cases"]
        for key, summary in fixtures.items():
            if summary != expected.get(key):
                problems.append(f"{key}: differs from frozen fixture")
    result = dict(
        schema="agv-wepa-golden-v1",
        repeats=args.repeats,
        deterministic=not problems,
        cases=fixtures,
        problems=problems,
        excluded_fields=["row.cpu", "row.wall", "config", "implementation_sha256"],
        archive_sha256=(
            hashlib.sha256(args.archive.read_bytes()).hexdigest() if args.archive else None
        ),
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if problems:
        raise SystemExit("; ".join(problems))
    print(f"PASS: {len(fixtures)} cases, {len(rows)} independent replays", flush=True)


if __name__ == "__main__":
    main()
