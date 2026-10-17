#!/usr/bin/env python3
"""Replay retained V9.1 traces against current source, without relaxing equality.

Default: replay every traces/*.json from a completed benchmark directory.
Use repeated --trace BASENAME only for an explicitly labelled subset smoke check.
Only genuine cpu_seconds/wall_seconds/decision_cpu_seconds fields are ignored.
All trajectories, metrics, logs and remaining metadata must match exactly.
"""

import argparse
import hashlib
import json
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from agv.dispatch.registry import run_named
from agv.evaluation.validation import validate
from agv.experiments.v91_bench import source_hashes
from agv.io.scenes import scenario_id, unpack_scene

ROOT = Path(__file__).resolve().parents[1]
TIMER_FIELDS = frozenset({"cpu_seconds", "wall_seconds", "decision_cpu_seconds"})


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def without_timers(value):
    if isinstance(value, dict):
        return {key: without_timers(item) for key, item in value.items() if key not in TIMER_FIELDS}
    if isinstance(value, (list, tuple)):
        return [without_timers(item) for item in value]
    return value


def _first_difference(before, after, path="result"):
    if type(before) is not type(after):
        return dict(
            path=path, kind="type", before=type(before).__name__, after=type(after).__name__
        )
    if isinstance(before, dict):
        if before.keys() != after.keys():
            return dict(
                path=path,
                kind="keys",
                missing=sorted(before.keys() - after.keys()),
                extra=sorted(after.keys() - before.keys()),
            )
        for key in sorted(before):
            found = _first_difference(before[key], after[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(before, list):
        if len(before) != len(after):
            return dict(path=path, kind="length", before=len(before), after=len(after))
        for index, (a, b) in enumerate(zip(before, after)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
    elif _canonical(before) != _canonical(after):
        return dict(path=path, kind="value", before=before, after=after)
    return None


def _git_commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _check_sources(expected):
    if source_hashes() != expected:
        raise RuntimeError("Source changed during the release replay audit")


def _replay_one(job):
    path, expected_sha, sources, solvers = job
    path = Path(path)
    row = dict(
        trace=f"traces/{path.name}",
        input_sha256=expected_sha,
        solver=None,
        registry_name=None,
        scenario_sha256=None,
        original_validated=False,
        replay_validated=False,
        before_result_sha256=None,
        after_result_sha256=None,
        results_equal=False,
        difference=None,
        error=None,
    )
    try:
        _check_sources(sources)
        raw = path.read_bytes()
        if _sha(raw) != expected_sha:
            raise ValueError("Input trace changed before replay")
        archive = json.loads(raw)
        scene = unpack_scene(archive)
        config, before = archive["config"], archive["result"]
        registry = config["registry_name"]
        if not isinstance(registry, str) or solvers.get(config["solver"]) != registry:
            raise ValueError("Trace registry_name differs from the saved protocol")
        row.update(
            solver=config["solver"], registry_name=registry, scenario_sha256=scenario_id(scene)
        )
        row["before_unfiltered_result_sha256"] = _sha(_canonical(before))
        old = without_timers(before)
        row["before_result_sha256"] = _sha(_canonical(old))
        validate(scene, before)
        row["original_validated"] = True
        original_scene_id = scenario_id(scene)
        after = run_named(registry, scene)
        if scenario_id(scene) != original_scene_id:
            raise ValueError("Replay mutated the supplied scene")
        validate(scene, after)
        row["replay_validated"] = True
        row["after_unfiltered_result_sha256"] = _sha(_canonical(after))
        new = without_timers(after)
        row["after_result_sha256"] = _sha(_canonical(new))
        # Canonical JSON also distinguishes booleans, integers and floats.
        # No numeric tolerance and no metadata subset are permitted here.
        row["results_equal"] = _canonical(old) == _canonical(new)
        if not row["results_equal"]:
            row["difference"] = _first_difference(old, new)
            row["error"] = "full_result_difference"
        _check_sources(sources)
        if _sha(path.read_bytes()) != expected_sha:
            raise ValueError("Input trace changed during replay")
    except Exception as error:
        row["results_equal"] = False
        row["error"] = f"{type(error).__name__}:{error}"
    return row


def audit_release(directory, output, *, workers=1, traces=None):
    """Write a non-overwriting audit; failures remain explicit in its JSON."""
    root, output = Path(directory), Path(output)
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError("workers must be an integer from 1 to 32")
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing release audit")
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Audit output must be outside the completed benchmark directory")
    manifest_path, protocol_path = root / "manifest.json", root / "protocol.json"
    manifest_raw, protocol_raw = manifest_path.read_bytes(), protocol_path.read_bytes()
    manifest, protocol = json.loads(manifest_raw), json.loads(protocol_raw)
    if manifest.get("schema") != "agv-v91-results-v1" or manifest.get("status") != "complete":
        raise ValueError("Release replay requires a completed V9.1 benchmark directory")
    artifacts = manifest.get("artifact_hashes", {})
    if _sha(protocol_raw) != artifacts.get("protocol.json") or _sha(protocol_raw) != manifest.get(
        "protocol_file_sha256"
    ):
        raise ValueError("Saved protocol hash differs from benchmark manifest")
    solvers = protocol.get("solvers")
    if not isinstance(solvers, dict):
        raise ValueError("Missing saved solver registry mapping")
    inventory = sorted((root / "traces").glob("*.json"))
    if not inventory or len(inventory) != manifest.get("representative_traces"):
        raise ValueError("Missing or incomplete representative trace inventory")
    names = {path.name: path for path in inventory}
    selected = inventory
    if traces is not None:
        if (
            not traces
            or len(traces) != len(set(traces))
            or any(name not in names for name in traces)
        ):
            raise ValueError("Explicit trace selection must contain distinct retained basenames")
        selected = [names[name] for name in traces]
    frozen = source_hashes()
    script_sha = _sha(Path(__file__).read_bytes())
    start_commit = _git_commit()
    jobs = []
    for path in selected:
        digest = _sha(path.read_bytes())
        if digest != artifacts.get(f"traces/{path.name}"):
            raise ValueError(f"Trace differs from benchmark manifest: {path.name}")
        jobs.append((str(path.resolve()), digest, frozen, solvers))
    rows = []
    if workers == 1:
        results = map(_replay_one, jobs)
        for row in results:
            rows.append(row)
            print(
                f"[{len(rows)}/{len(jobs)}] {row['trace']}: {row['error'] or 'match'}", flush=True
            )
    else:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            for row in pool.map(_replay_one, jobs):
                rows.append(row)
                print(
                    f"[{len(rows)}/{len(jobs)}] {row['trace']}: {row['error'] or 'match'}",
                    flush=True,
                )
    ending_sources = source_hashes()
    ending_script_sha = _sha(Path(__file__).read_bytes())
    inputs_unchanged = (
        _sha(manifest_path.read_bytes()) == _sha(manifest_raw)
        and _sha(protocol_path.read_bytes()) == _sha(protocol_raw)
        and sorted(path.name for path in (root / "traces").glob("*.json")) == sorted(names)
        and all(_sha(Path(path).read_bytes()) == digest for path, digest, _, _ in jobs)
    )
    stable = ending_sources == frozen and ending_script_sha == script_sha
    success = (
        stable
        and inputs_unchanged
        and len(rows) == len(jobs)
        and all(row["results_equal"] and row["error"] is None for row in rows)
    )
    original_sources = manifest.get("source_hashes", {})
    report = dict(
        schema="agv-v91-release-replay-v1",
        created_at=datetime.now(timezone.utc).isoformat(),
        complete=success,
        scope="all_retained_representative_traces" if traces is None else "explicit_trace_subset",
        benchmark_name=root.name,
        input_manifest_sha256=_sha(manifest_raw),
        input_protocol_sha256=_sha(protocol_raw),
        benchmark_git_commit=manifest.get("git_commit"),
        git_commit=start_commit,
        git_commit_at_end=_git_commit(),
        source_hashes=frozen,
        source_hashes_at_end=ending_sources,
        source_hash_mode="utf8-text-LF-normalized-sha256",
        benchmark_source_hashes=original_sources,
        changed_source_files=sorted(
            name
            for name in set(frozen) | set(original_sources)
            if frozen.get(name) != original_sources.get(name)
        ),
        script_sha256=script_sha,
        script_sha256_at_end=ending_script_sha,
        source_and_script_unchanged=stable,
        inputs_unchanged=inputs_unchanged,
        workers=workers,
        ignored_timer_fields=sorted(TIMER_FIELDS),
        result_hash_scope="Entire result after recursive removal of listed genuine timer fields only",
        available_trace_count=len(inventory),
        selected_trace_count=len(jobs),
        matched_trace_count=sum(row["results_equal"] and row["error"] is None for row in rows),
        failed_trace_count=sum(
            not row["results_equal"] or row["error"] is not None for row in rows
        ),
        traces=rows,
        limitation="Representative first-seed trace replay, not every benchmark run or a new performance sample",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--trace", action="append", help="Smoke check only: retained trace basename"
    )
    args = parser.parse_args()
    report = audit_release(args.directory, args.output, workers=args.workers, traces=args.trace)
    print(
        f"Matched {report['matched_trace_count']}/{report['selected_trace_count']} retained traces; "
        f"source stable={report['source_and_script_unchanged']}; audit={args.output}",
        flush=True,
    )
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
