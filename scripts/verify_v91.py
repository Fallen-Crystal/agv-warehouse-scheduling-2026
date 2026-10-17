#!/usr/bin/env python3
"""Independently audit V9.1 hashes, matrix, paired arithmetic and saved traces."""

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
from pathlib import Path

from agv.evaluation.validation import validate
from agv.experiments.v91_bench import (
    METRICS,
    PROTOCOL_SCHEMA,
    RESULT_SCHEMA,
    build_scene,
    read_rows,
    validate_protocol,
)
from agv.io.scenes import scenario_id, unpack_scene

ROOT = Path(__file__).resolve().parents[1]


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def source_hashes(revision=None):
    """Independent inventory, using the same declared LF text normalization."""
    suffixes = (".py", ".json", ".js", ".html", ".css")
    if revision is None:
        paths = [p for p in (ROOT / "src/agv").rglob("*") if p.is_file() and p.suffix in suffixes]
        paths.append(ROOT / "scripts/verify_v91.py")
        contents = [(p.relative_to(ROOT).as_posix(), p.read_bytes()) for p in sorted(paths)]
    else:
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", revision, "src/agv", "scripts/verify_v91.py"],
            cwd=ROOT,
            text=True,
        ).splitlines()
        contents = [
            (name, subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=ROOT))
            for name in names
            if Path(name).suffix in suffixes
        ]
    return {
        name: _hash(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")) for name, raw in contents
    }


def _close(actual, expected):
    if expected is None:
        return actual is None
    if type(expected) in (int, float):
        return (
            type(actual) in (int, float)
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_close(a, b) for a, b in zip(actual, expected))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_close(actual[k], v) for k, v in expected.items())
        )
    return type(actual) is type(expected) and actual == expected


def _expect(actual, expected, label):
    if not _close(actual, expected):
        raise ValueError("Independent calculation differs: " + label)


def _mean(values):
    return statistics.mean(values) if values else None


def _bootstrap(values, boot):
    if not values:
        return None
    rng = random.Random(boot["seed"])
    n = len(values)
    means = sorted(
        sum(values[int(rng.random() * n)] for _ in range(n)) / n for _ in range(boot["resamples"])
    )
    return [means[math.floor(0.025 * (len(means) - 1))], means[math.ceil(0.975 * (len(means) - 1))]]


def _check_summary(rows, saved, protocol):
    baseline = protocol.get("baseline", "G0")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    templates = [f"{m}__{w}" for m in protocol["maps"] for w in protocol["workloads"]]
    expected_groups = {
        (template, solver) for template in templates + ["__all__"] for solver in protocol["solvers"]
    }
    groups = saved["groups"]
    keys = [(g["scenario"], g["solver"]) for g in groups]
    if len(keys) != len(expected_groups) or set(keys) != expected_groups:
        raise ValueError("Incomplete or duplicated summary groups")
    for group in groups:
        own = [
            r
            for r in rows
            if r["solver"] == group["solver"]
            and (group["scenario"] == "__all__" or r["scenario"] == group["scenario"])
        ]
        pairs = [(index[r["scenario"], r["seed"], baseline], r) for r in own]
        pairs = [
            (a, b)
            for a, b in pairs
            if a["comparison_valid"] and b["comparison_valid"] and a["backend"] == b["backend"]
        ]
        deltas = [b["weighted_score"] - a["weighted_score"] for a, b in pairs]
        checks = dict(
            comparison_role=(
                "score_reference_diagnostic"
                if protocol["solvers"][group["solver"]] == "baseline"
                else "same_sipp_control"
            ),
            runs=len(own),
            successes=sum(r["comparison_valid"] for r in own),
            execution_failures=sum(not r["execution_valid"] or not r["feasible"] for r in own),
            paired_successes=len(pairs),
            excluded_pairs=len(own) - len(pairs),
            score_wins=sum(d < -1e-12 for d in deltas),
            score_losses=sum(d > 1e-12 for d in deltas),
            score_ties=sum(abs(d) <= 1e-12 for d in deltas),
            p90_degradations=sum(b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs),
            max_response_degradations=sum(
                b["max_flow_time"] > a["max_flow_time"] for a, b in pairs
            ),
            paired_F_difference_mean=_mean(deltas),
            cpu_seconds_mean_all_runs=_mean([r["cpu_seconds"] for r in own]),
            cpu_ratio_mean=_mean(
                [b["cpu_seconds"] / a["cpu_seconds"] for a, b in pairs if a["cpu_seconds"] > 0]
            ),
        )
        for metric in METRICS:
            effects = [(1 - b[metric] / a[metric]) * 100 for a, b in pairs if a[metric] > 0]
            checks[metric + "_mean_paired"] = _mean([b[metric] for _, b in pairs])
            checks[metric + "_improvement_pct_mean"] = _mean(effects)
            checks[metric + "_improvement_pct_95ci"] = _bootstrap(effects, protocol["bootstrap"])
            checks[metric + "_effect_pairs"] = len(effects)
        checks["paired_F_improvement_pct_mean"] = checks["weighted_score_improvement_pct_mean"]
        checks["paired_F_improvement_pct_95ci"] = checks["weighted_score_improvement_pct_95ci"]
        for key, expected in checks.items():
            _expect(group.get(key), expected, f"{group['scenario']}/{group['solver']}/{key}")
    equal = saved["template_equal"]
    if len(equal) != len(protocol["solvers"]) or {g["solver"] for g in equal} != set(
        protocol["solvers"]
    ):
        raise ValueError("Incomplete template-equal aggregates")
    for group in equal:
        values = [
            g["paired_F_improvement_pct_mean"]
            for g in groups
            if g["solver"] == group["solver"]
            and g["scenario"] != "__all__"
            and g["paired_F_improvement_pct_mean"] is not None
        ]
        _expect(group["included_templates"], len(values), "included templates")
        _expect(group["total_templates"], len(templates), "total templates")
        _expect(group["template_equal_F_improvement_pct_mean"], _mean(values), "equal F")


def verify(directory, revision=None):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != RESULT_SCHEMA or manifest.get("status") != "complete":
        raise ValueError("V9.1 experiment is not finalized")
    raw = (root / "protocol.json").read_bytes()
    protocol = json.loads(raw.decode("utf-8-sig"))
    validate_protocol(protocol)
    canonical = json.dumps(
        protocol, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or _hash(raw) != manifest["protocol_file_sha256"]
        or _hash(canonical) != manifest["protocol_sha256"]
    ):
        raise ValueError("Protocol hash mismatch")
    if manifest.get("source_hash_mode") != "utf8-text-LF-normalized-sha256":
        raise ValueError("Unknown source hash mode")
    if source_hashes(revision) != manifest["source_hashes"]:
        raise ValueError("Source snapshot differs from measured LF hashes")
    required = {"protocol.json", "runs.csv", "summary.json", "diagnostics.jsonl", "bounds.jsonl"}
    artifacts = manifest["artifact_hashes"]
    actual_files = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    if set(artifacts) != actual_files or not required <= set(artifacts):
        raise ValueError("Missing or untracked experiment artifacts")
    for name, digest in artifacts.items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or _hash(path.read_bytes()) != digest:
            raise ValueError("Changed artifact: " + name)
    rows = read_rows(root / "runs.csv")
    expected = {
        (f"{m}__{w}", seed, solver)
        for m in protocol["maps"]
        for w in protocol["workloads"]
        for seed in protocol["seeds"]
        for solver in protocol["solvers"]
    }
    keys = [(r["scenario"], r["seed"], r["solver"]) for r in rows]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("Incomplete or duplicated experiment matrix")
    _expect(manifest["expected_runs"], len(rows), "expected runs")
    _expect(manifest["recorded_runs"], len(rows), "recorded runs")
    index = dict(zip(keys, rows))
    digests = {}
    for m, map_options in protocol["maps"].items():
        for w, options in protocol["workloads"].items():
            for seed in protocol["seeds"]:
                scene = build_scene(map_options, options, seed)
                digests[f"{m}__{w}", seed] = scenario_id(scene)
    for row in rows:
        if row["scenario_sha256"] != digests[row["scenario"], row["seed"]]:
            raise ValueError("Scenario hash differs from protocol reconstruction")
        expected_backend = "astar" if row["registry_name"] == "baseline" else "sipp"
        if (
            row["registry_name"] != protocol["solvers"][row["solver"]]
            or row["backend"] != expected_backend
            or row["joint"]
        ):
            raise ValueError("Solver/backend differs from frozen protocol")
        if min(row["cpu_seconds"], row["wall_seconds"]) < 0:
            raise ValueError("Negative execution timing")
        references = [row["reference_" + key] for key in ("T", "R", "D")]
        f_bound = (
            sum(
                weight * row[key + "_lower_bound"] / row["reference_" + key]
                for weight, key in ((0.5, "T"), (0.3, "R"), (0.2, "D"))
            )
            if row["total_tasks"] and all(value is not None and value > 0 for value in references)
            else 0.0
            if not row["total_tasks"] and all(value is not None for value in references)
            else None
        )
        _expect(row["F_lower_bound"], f_bound, "F lower bound arithmetic")
        if row["comparison_valid"]:
            if not all(row[k] for k in ("execution_valid", "feasible", "score_valid")):
                raise ValueError("Invalid run included as comparable")
            if row["completed"] != row["total_tasks"]:
                raise ValueError("Partial execution included as comparable")
            expected_f = (
                0
                if not row["total_tasks"]
                else sum(
                    weight * row[metric] / row["reference_" + key]
                    for weight, metric, key in (
                        (0.5, "makespan", "T"),
                        (0.3, "mean_flow_time", "R"),
                        (0.2, "moves", "D"),
                    )
                )
            )
            _expect(row["weighted_score"], expected_f, "F arithmetic")
            for key, metric in (("T", "makespan"), ("R", "mean_flow_time"), ("D", "moves")):
                bound = row[key + "_lower_bound"]
                if bound < 0 or row[metric] + 1e-9 < bound:
                    raise ValueError("Claimed lower bound exceeds feasible result")
                _expect(
                    row[key + "_gap_pct"],
                    100 * (row[metric] / bound - 1) if bound else None,
                    key + " gap",
                )
            _expect(
                row["F_gap_pct"],
                100 * (row["weighted_score"] / f_bound - 1)
                if f_bound is not None and f_bound > 0
                else None,
                "F gap",
            )
        elif any(row[k] is not None for k in METRICS if k not in ("cpu_seconds", "wall_seconds")):
            raise ValueError("Failed run exposes comparable full-task costs")
        if not row["comparison_valid"] and (
            row["F_gap_pct"] is not None
            or any(row[key + "_gap_pct"] is not None for key in ("T", "R", "D"))
        ):
            raise ValueError("Failed run exposes a misleading lower-bound gap")
    _expect(manifest["comparable_runs"], sum(r["comparison_valid"] for r in rows), "successes")
    _expect(
        manifest["execution_failures"],
        sum(not r["execution_valid"] or not r["feasible"] for r in rows),
        "failures",
    )
    saved = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    _check_summary(rows, saved, protocol)
    diagnostics = [
        json.loads(line)
        for line in (root / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    diagnostic_keys = [(r["scenario"], r["seed"], r["solver"]) for r in diagnostics]
    if len(diagnostic_keys) != len(expected) or set(diagnostic_keys) != expected:
        raise ValueError("Incomplete per-run diagnostics")
    evidence = [
        json.loads(line)
        for line in (root / "bounds.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    bound_index = {(r["scenario"], r["seed"]): r for r in evidence}
    if len(evidence) != len(digests) or set(bound_index) != set(digests):
        raise ValueError("Incomplete lower-bound evidence")
    for row in rows:
        item = bound_index[row["scenario"], row["seed"]]
        _expect(item["scenario_sha256"], row["scenario_sha256"], "bound scenario")
        for key in ("T", "R", "D"):
            _expect(item["bounds"][key], row[key + "_lower_bound"], "bound column")
    trace_expected = {(scenario, protocol["seeds"][0], solver) for scenario, _, solver in expected}
    seen, valid, failed = set(), 0, 0
    for path in sorted((root / "traces").glob("*.json")):
        archive = json.loads(path.read_text(encoding="utf-8"))
        scene = unpack_scene(archive)
        config = archive["config"]
        key = config["scenario"], config["seed"], config["solver"]
        if key not in trace_expected or key in seen:
            raise ValueError("Unexpected or duplicated representative trace")
        seen.add(key)
        row = index[key]
        _expect(scenario_id(scene), row["scenario_sha256"], "trace scene")
        if archive["experiment_audit"]["execution_valid"]:
            validate(scene, archive["result"])
            valid += 1
            if row["comparison_valid"]:
                for metric in METRICS:
                    if metric not in ("cpu_seconds", "wall_seconds"):
                        _expect(archive["result"][metric], row[metric], "trace " + metric)
        elif not row["execution_valid"] and archive["experiment_audit"].get("error"):
            failed += 1
        else:
            raise ValueError("Trace failure evidence inconsistent")
    if seen != trace_expected or len(seen) != manifest["representative_traces"]:
        raise ValueError("Missing representative traces")
    return dict(
        status="verified",
        rows=len(rows),
        independent_traces_validated=valid,
        retained_failed_traces=failed,
        source_revision=revision or "current",
        protocol_sha256=manifest["protocol_sha256"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--revision")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.revision), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
