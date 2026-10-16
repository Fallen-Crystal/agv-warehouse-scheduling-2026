#!/usr/bin/env python3
"""Verify event-driven shadow implementation equivalence, not new quality evidence.

Requires all four original/event holdout/generalization manifests to be complete.
Compares every recorded non-timing CSV field, plus complete representative trace
results after removing timing fields and the algorithm's event_driven flag only.
No policy is run. Add --validate-traces for the independent execution validator;
otherwise use this alongside the project's separate full result audit.
"""

import argparse
import hashlib
import json
import math
import statistics
import subprocess
from functools import lru_cache
from pathlib import Path

from agv.experiments.bcrd import protocol_id, read_rows, validate_protocol
from agv.io.scenes import scenario_id, unpack_scene

ROOT = Path(__file__).resolve().parents[1]
TIMING_FIELDS = frozenset({"cpu_seconds", "wall_seconds", "decision_cpu_seconds"})
COMMON_SOLVERS = ("G0", "G1", "G2")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _revision(value):
    return subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{value}^{{commit}}"], cwd=ROOT, text=True
    ).strip()


@lru_cache(maxsize=4)
def _revision_sources(revision):
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", revision, "src/agv"], cwd=ROOT, text=True
    ).splitlines()
    hashes = {}
    for name in names:
        if Path(name).suffix in (".py", ".json", ".js", ".html", ".css"):
            raw = subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=ROOT)
            hashes[str(Path(name).relative_to("src/agv"))] = hashlib.sha256(raw).hexdigest()
    return hashes


def _new_diff():
    return dict(
        compared_numeric_values=0,
        maximum_absolute_difference=0.0,
        maximum_relative_difference=0.0,
        largest_difference_path=None,
    )


def assert_equal(a, b, *, path="value", differences=None):
    """Strict structure/types, with finite numerical tolerance 1e-12."""
    differences = _new_diff() if differences is None else differences
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            raise ValueError(f"Different fields at {path}: {set(a) ^ set(b)}")
        for key in a:
            assert_equal(a[key], b[key], path=f"{path}.{key}", differences=differences)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            raise ValueError(f"Different lengths at {path}: {len(a)} != {len(b)}")
        for i, (left, right) in enumerate(zip(a, b)):
            assert_equal(left, right, path=f"{path}[{i}]", differences=differences)
    elif type(a) in (int, float) and type(b) in (int, float):
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError(f"Nonfinite value at {path}")
        absolute = abs(a - b)
        relative = absolute / max(1.0, abs(a), abs(b))
        differences["compared_numeric_values"] += 1
        if absolute > differences["maximum_absolute_difference"]:
            differences["maximum_absolute_difference"] = absolute
            differences["largest_difference_path"] = path
        differences["maximum_relative_difference"] = max(
            differences["maximum_relative_difference"], relative
        )
        if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"Different numbers at {path}: {a!r} != {b!r}")
    elif type(a) is not type(b) or a != b:
        raise ValueError(f"Different values at {path}: {a!r} != {b!r}")
    return differences


def _strip_timing(value):
    if isinstance(value, dict):
        return {key: _strip_timing(item) for key, item in value.items() if key not in TIMING_FIELDS}
    if isinstance(value, list):
        return [_strip_timing(item) for item in value]
    return value


def _trace_result(result):
    clean = _strip_timing(result)
    if isinstance(clean.get("algorithm"), dict):
        clean["algorithm"].pop("event_driven", None)
    return clean


def _load(directory, expected_revision=None):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "agv-bcrd-results-v1" or manifest.get("status") != "complete":
        raise ValueError(f"Matrix is not complete: {root}")
    raw = (root / "protocol.json").read_bytes()
    protocol = json.loads(raw.decode("utf-8-sig"))
    validate_protocol(protocol, require_frozen=True)
    if (
        protocol_id(protocol) != manifest["protocol_sha256"]
        or hashlib.sha256(raw).hexdigest() != manifest["protocol_file_sha256"]
    ):
        raise ValueError(f"Protocol hash differs: {root}")
    revision = _revision(manifest["git_commit"])
    if expected_revision is not None and revision != _revision(expected_revision):
        raise ValueError(f"Unexpected measured revision: {root}")
    if _revision_sources(revision) != manifest["source_hashes"]:
        raise ValueError(f"Measured source does not match its Git snapshot: {root}")
    for name, digest in manifest["artifact_hashes"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or _sha(path) != digest:
            raise ValueError(f"Changed/invalid artifact: {root}/{name}")
    rows = read_rows(root / "runs.csv")
    expected = {
        (name, seed, solver)
        for name in protocol["configs"]
        for seed in protocol["seeds"]
        for solver in protocol["solvers"]
    }
    index = {(row["scenario"], row["seed"], row["solver"]): row for row in rows}
    if (
        len(rows) != len(index)
        or set(index) != expected
        or len(rows) != manifest["expected_runs"]
        or len(rows) != manifest["recorded_runs"]
    ):
        raise ValueError(f"Incomplete/duplicated matrix: {root}")
    if manifest["execution_failures"] != 0 or manifest["comparable_runs"] != len(rows):
        raise ValueError(f"Failures cannot be ignored for equivalence: {root}")
    for key, row in index.items():
        if (
            not all(
                row.get(field) is True
                for field in ("execution_valid", "feasible", "comparison_valid", "score_valid")
            )
            or row["completed"] != row["total_tasks"]
            or row["completion_rate"] != 1
        ):
            raise ValueError(f"Failed/incomparable row: {root} {key}")
    return dict(
        root=root,
        protocol=protocol,
        manifest=manifest,
        revision=revision,
        index=index,
        provenance=dict(
            directory=str(root),
            git_commit=revision,
            rows=len(rows),
            protocol_sha256=manifest["protocol_sha256"],
            protocol_file_sha256=manifest["protocol_file_sha256"],
            manifest_file_sha256=_sha(root / "manifest.json"),
            csv_file_sha256=_sha(root / "runs.csv"),
        ),
    )


def _quality_params(params):
    return {key: value for key, value in params.items() if key != "event_driven"}


def _check_protocols(old, event):
    a, b = old["protocol"], event["protocol"]
    for field in ("split", "seeds", "configs", "baseline", "bootstrap", "source_plan", "criteria"):
        assert_equal(a.get(field), b.get(field), path=f"protocol.{field}")
    if set(b["solvers"]) != set(COMMON_SOLVERS) | {"G2_stepwise"}:
        raise ValueError("Event matrix must contain G0/G1/G2/G2_stepwise without omitted runs")
    for solver in COMMON_SOLVERS:
        assert_equal(
            _quality_params(a["solvers"][solver]),
            _quality_params(b["solvers"][solver]),
            path=f"protocol.solvers.{solver}",
        )
    assert_equal(
        _quality_params(b["solvers"]["G2"]),
        _quality_params(b["solvers"]["G2_stepwise"]),
        path="protocol.G2_vs_stepwise",
    )
    if (
        b["solvers"]["G2"].get("event_driven") is not True
        or b["solvers"]["G2_stepwise"].get("event_driven") is not False
    ):
        raise ValueError("Event and stepwise implementation flags must be explicit")
    frozen_at = b.get("implementation_validation", {}).get("quality_parameters_frozen_at")
    if frozen_at is not None and _revision(frozen_at) != old["revision"]:
        raise ValueError("Event protocol does not identify the original quality freeze")


def compare_rows(left, right, *, left_solver=None, right_solver=None):
    """Compare complete indexed pairs; timing and the solver label alone may differ."""
    if len(left) != len(right) or not left:
        raise ValueError("Missing or empty paired rows")
    differences = _new_diff()
    field_maxima, fields = {}, None
    for key in sorted(left):
        if key not in right:
            raise ValueError(f"Missing paired row {key}")
        a, b = left[key], right[key]
        if left_solver is not None and a["solver"] != left_solver:
            raise ValueError("Wrong left policy in pair")
        if right_solver is not None and b["solver"] != right_solver:
            raise ValueError("Wrong right policy in pair")
        a = {k: v for k, v in a.items() if k not in TIMING_FIELDS and k != "solver"}
        b = {k: v for k, v in b.items() if k not in TIMING_FIELDS and k != "solver"}
        if fields is None:
            fields = sorted(a)
        assert_equal(a, b, path=str(key), differences=differences)
        for field, value in a.items():
            if type(value) in (int, float):
                field_maxima[field] = max(field_maxima.get(field, 0), abs(value - b[field]))
    return dict(
        pairs=len(left),
        compared_fields=fields,
        ignored_timing_fields=sorted(TIMING_FIELDS),
        numeric_max_absolute_by_field=field_maxima,
        **differences,
    )


def _read_trace(matrix, scenario, solver, do_validate):
    path = matrix["root"] / "traces" / f"{scenario}-{solver}.json"
    if str(path.relative_to(matrix["root"])) not in matrix["manifest"]["artifact_hashes"]:
        raise ValueError(f"Representative trace is missing from artifact provenance: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    scene = unpack_scene(raw)
    config = raw["config"]
    key = (scenario, matrix["protocol"]["seeds"][0], solver)
    row = matrix["index"][key]
    if (
        config["scenario"] != scenario
        or config["seed"] != key[1]
        or config["solver"] != solver
        or raw["scenario_sha256"] != row["scenario_sha256"]
        or scenario_id(scene) != row["scenario_sha256"]
    ):
        raise ValueError(f"Trace is not the representative paired input: {path}")
    if raw["experiment_audit"] != {"execution_valid": True, "error": None}:
        raise ValueError(f"Failed trace cannot be skipped: {path}")
    if do_validate:
        from agv.evaluation.validation import validate

        validate(scene, raw["result"])
    return raw, dict(path=str(path), sha256=_sha(path))


def _speed_summary(event):
    index = event["index"]
    groups = []
    names = list(event["protocol"]["configs"])
    for name in names + ["__all__"]:
        keys = [
            (scenario, seed)
            for scenario in names
            if name == "__all__" or scenario == name
            for seed in event["protocol"]["seeds"]
        ]
        triples = [
            (
                index[scenario, seed, "G0"],
                index[scenario, seed, "G2"],
                index[scenario, seed, "G2_stepwise"],
            )
            for scenario, seed in keys
        ]
        for triple in triples:
            if any(row["cpu_seconds"] <= 0 or row["wall_seconds"] <= 0 for row in triple):
                raise ValueError("Timing ratios require positive measured times")
        speedups = [
            step["cpu_seconds"] / accelerated["cpu_seconds"] for _, accelerated, step in triples
        ]
        groups.append(
            dict(
                scenario=name,
                pairs=len(triples),
                cpu_stepwise_over_event_pair_mean=statistics.mean(speedups),
                cpu_stepwise_over_event_pair_min=min(speedups),
                cpu_stepwise_over_event_pair_max=max(speedups),
                cpu_stepwise_over_event_ratio_of_means=statistics.mean(
                    step["cpu_seconds"] for _, _, step in triples
                )
                / statistics.mean(acc["cpu_seconds"] for _, acc, _ in triples),
                event_cpu_over_G0_pair_mean=statistics.mean(
                    acc["cpu_seconds"] / base["cpu_seconds"] for base, acc, _ in triples
                ),
                stepwise_cpu_over_G0_pair_mean=statistics.mean(
                    step["cpu_seconds"] / base["cpu_seconds"] for base, _, step in triples
                ),
                event_cpu_seconds_mean=statistics.mean(acc["cpu_seconds"] for _, acc, _ in triples),
                stepwise_cpu_seconds_mean=statistics.mean(
                    step["cpu_seconds"] for _, _, step in triples
                ),
                G0_cpu_seconds_mean=statistics.mean(base["cpu_seconds"] for base, _, _ in triples),
                event_wall_seconds_mean=statistics.mean(
                    acc["wall_seconds"] for _, acc, _ in triples
                ),
                stepwise_wall_seconds_mean=statistics.mean(
                    step["wall_seconds"] for _, _, step in triples
                ),
                G0_wall_seconds_mean=statistics.mean(
                    base["wall_seconds"] for base, _, _ in triples
                ),
            )
        )
    return groups


def _overall_speed(event_matrices):
    triples = []
    for matrix in event_matrices:
        index = matrix["index"]
        triples.extend(
            (index[name, seed, "G0"], index[name, seed, "G2"], index[name, seed, "G2_stepwise"])
            for name in matrix["protocol"]["configs"]
            for seed in matrix["protocol"]["seeds"]
        )
    return dict(
        pairs=len(triples),
        weighting="Equal weight per paired instance across both reused splits",
        cpu_stepwise_over_event_pair_mean=statistics.mean(
            step["cpu_seconds"] / event["cpu_seconds"] for _, event, step in triples
        ),
        event_cpu_over_G0_pair_mean=statistics.mean(
            event["cpu_seconds"] / base["cpu_seconds"] for base, event, _ in triples
        ),
        stepwise_cpu_over_G0_pair_mean=statistics.mean(
            step["cpu_seconds"] / base["cpu_seconds"] for base, _, step in triples
        ),
        event_wall_seconds_mean=statistics.mean(event["wall_seconds"] for _, event, _ in triples),
        stepwise_wall_seconds_mean=statistics.mean(step["wall_seconds"] for _, _, step in triples),
        G0_wall_seconds_mean=statistics.mean(base["wall_seconds"] for base, _, _ in triples),
    )


def verify(root="results/bcrd", *, old_revision=None, event_revision=None, validate_traces=False):
    root = Path(root)
    old_h = _load(root / "holdout", old_revision)
    old_g = _load(root / "generalization", old_revision or old_h["revision"])
    event_h = _load(root / "event-holdout", event_revision)
    event_g = _load(root / "event-generalization", event_revision or event_h["revision"])
    if old_h["revision"] == event_h["revision"]:
        raise ValueError("Old and event implementation snapshots must be distinguished")
    comparisons, traces, sources = [], [], []
    total_legacy_pairs = total_event_pairs = 0
    for label, old, event in (("holdout", old_h, event_h), ("generalization", old_g, event_g)):
        _check_protocols(old, event)
        old_rows = {key: value for key, value in old["index"].items() if key[2] in COMMON_SOLVERS}
        new_rows = {key: value for key, value in event["index"].items() if key[2] in COMMON_SOLVERS}
        legacy = compare_rows(old_rows, new_rows)
        event_rows = {(k[0], k[1]): v for k, v in event["index"].items() if k[2] == "G2"}
        step_rows = {(k[0], k[1]): v for k, v in event["index"].items() if k[2] == "G2_stepwise"}
        accelerated = compare_rows(
            event_rows, step_rows, left_solver="G2", right_solver="G2_stepwise"
        )
        total_legacy_pairs += legacy["pairs"]
        total_event_pairs += accelerated["pairs"]
        comparisons.append(dict(split=label, old_vs_event=legacy, event_vs_stepwise=accelerated))
        for scenario in event["protocol"]["configs"]:
            for solver in COMMON_SOLVERS:
                a, a_source = _read_trace(old, scenario, solver, validate_traces)
                b, b_source = _read_trace(event, scenario, solver, validate_traces)
                difference = assert_equal(
                    _trace_result(a["result"]),
                    _trace_result(b["result"]),
                    path=f"{label}.{scenario}.{solver}",
                )
                traces.append(
                    dict(
                        split=label,
                        scenario=scenario,
                        left="old-" + solver,
                        right="event-" + solver,
                        **difference,
                    )
                )
                sources.extend((a_source, b_source))
            a, a_source = _read_trace(event, scenario, "G2", validate_traces)
            b, b_source = _read_trace(event, scenario, "G2_stepwise", validate_traces)
            difference = assert_equal(
                _trace_result(a["result"]),
                _trace_result(b["result"]),
                path=f"{label}.{scenario}.event_vs_stepwise",
            )
            traces.append(
                dict(split=label, scenario=scenario, left="G2", right="G2_stepwise", **difference)
            )
            sources.extend((a_source, b_source))
    return dict(
        schema="agv-bcrd-event-equivalence-v1",
        status="equivalent",
        evidence_scope="These exact quality seeds were used before the implementation change. This is behavior-equivalence and descriptive CPU evidence only, NOT a second independent held-out quality evaluation.",
        quality_parameters_changed=False,
        old_git_commit=old_h["revision"],
        event_git_commit=event_h["revision"],
        all_matrix_runs_retained=True,
        failed_runs=0,
        old_vs_event_row_pairs=total_legacy_pairs,
        event_vs_stepwise_row_pairs=total_event_pairs,
        trace_pairs=len(traces),
        maximum_absolute_quality_difference=max(
            [
                item[side]["maximum_absolute_difference"]
                for item in comparisons
                for side in ("old_vs_event", "event_vs_stepwise")
            ]
            + [item["maximum_absolute_difference"] for item in traces]
        ),
        independent_trace_validation=validate_traces,
        ignored_trace_fields="Only cpu_seconds/wall_seconds/decision_cpu_seconds recursively, plus algorithm.event_driven; all other result fields compared, including paths, interval_states, assignments, events, complete candidate decisions and routing counters.",
        comparisons=comparisons,
        trace_comparisons=traces,
        cpu_statistics=dict(
            aggregation="Within-scenario arithmetic means of paired ratios; __all__ is equal weight per instance. Ratios of means are separately labelled. One timing per policy-instance; CPU/wall are descriptive, not confidence bounds.",
            holdout=_speed_summary(event_h),
            generalization=_speed_summary(event_g),
            all_paired_instances=_overall_speed((event_h, event_g)),
        ),
        provenance=[matrix["provenance"] for matrix in (old_h, old_g, event_h, event_g)],
        representative_trace_sources=list({entry["path"]: entry for entry in sources}.values()),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="results/bcrd", type=Path)
    parser.add_argument("--old-revision")
    parser.add_argument("--event-revision")
    parser.add_argument("--validate-traces", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(
        args.root,
        old_revision=args.old_revision,
        event_revision=args.event_revision,
        validate_traces=args.validate_traces,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
