"""Recheck V4 evidence without rerunning or changing the measured experiments.

Run from any directory after installing the project. Optional private input
paths are hashed locally; published provenance contains only relative names.
CSV rows have metric/identity checks. Saved traces additionally receive the
independent trajectory, layer, station, service and objective auditor.
"""

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from agv.evaluation.objective import reference_context
from agv.evaluation.validation import validate
from agv.experiments.benchmark import source_hashes
from agv.io.scenes import scenario_id, unpack_scene
from agv.warehouse.layout import generate

ROOT = Path(__file__).resolve().parents[1]
COSTS = ("makespan", "mean_flow_time", "p90_flow_time", "moves", "weighted_score")
INT_FIELDS = (
    "seed",
    "completed",
    "total_tasks",
    "makespan",
    "time",
    "moves",
    "empty_moves",
    "loaded_moves",
    "traffic_wait_steps",
    "replan_calls",
    "accepted_replans",
)
BOOL_FIELDS = ("feasible", "score_valid")
TEXT_FIELDS = ("scenario", "solver", "scenario_sha256")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, label):
    require(
        math.isfinite(actual)
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-11),
        f"Metric mismatch: {label}: {actual!r} != {expected!r}",
    )


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_row(raw):
    row = {}
    for key, value in raw.items():
        if key in TEXT_FIELDS:
            row[key] = value
        elif key in INT_FIELDS:
            row[key] = int(value)
        elif key in BOOL_FIELDS:
            require(value in ("True", "False"), "Invalid boolean in " + key)
            row[key] = value == "True"
        else:
            row[key] = float(value)
            require(math.isfinite(row[key]), "Nonfinite CSV value in " + key)
    return row


def independent_summary(rows, manifest):
    """Rebuild all published summaries from CSV, without the benchmark helper."""
    answer = []
    for name in manifest["configs"]:
        baseline = {
            row["seed"]: row
            for row in rows
            if row["scenario"] == name and row["solver"] == "baseline"
        }
        for solver in manifest["solvers"]:
            own = [r for r in rows if r["scenario"] == name and r["solver"] == solver]
            pairs = [
                (baseline[r["seed"]], r)
                for r in own
                if r["feasible"] and r["score_valid"] and baseline[r["seed"]]["feasible"]
            ]
            item = {
                "scenario": name,
                "solver": solver,
                "runs": len(own),
                "successes": sum(r["feasible"] for r in own),
                "paired_successes": len(pairs),
                "runtime_mean": statistics.mean(r["runtime_seconds"] for r in own),
            }
            for field in COSTS:
                before = [a[field] for a, _ in pairs]
                after = [b[field] for _, b in pairs]
                item[field + "_mean"] = statistics.mean(after)
                item[field + "_improvement_pct"] = 100 * (sum(before) - sum(after)) / sum(before)
            item["score_wins"] = sum(b["weighted_score"] < a["weighted_score"] for a, b in pairs)
            answer.append(item)
    return answer


def audit(root, example_path):
    manifest = read_json(root / "manifest.json")
    require(manifest["status"] == "complete", "Incomplete benchmark")
    require(manifest["source_hashes"] == source_hashes(), "Measured source snapshot has drifted")
    with (root / "runs.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = [parse_row(raw) for raw in csv.DictReader(file)]
    expected = {
        (name, seed, solver)
        for name in manifest["configs"]
        for seed in manifest["seeds"]
        for solver in manifest["solvers"]
    }
    by_key = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    require(len(by_key) == len(rows) == len(expected), "Missing/duplicate experiment rows")
    require(set(by_key) == expected, "Unexpected experiment identity")
    require(len(rows) == manifest["validated_runs"], "Wrong manifest validated count")
    require(
        sum(r["feasible"] for r in rows) == manifest["successful_runs"],
        "Wrong manifest success count",
    )
    scenes = {}
    for (name, seed, solver), row in by_key.items():
        key = (name, seed)
        if key not in scenes:
            scene = generate(**manifest["configs"][name], seed=seed)
            # This reproduces the trusted reference only, not all candidate runs.
            context = reference_context(scene)
            scenes[key] = (scene, context)
            require(context["available"], "Reference failed: " + str(key))
        scene, context = scenes[key]
        require(row["scenario_sha256"] == scenario_id(scene), "Scene identity changed")
        require(row["feasible"] and row["score_valid"], "Unsuccessful row in this evidence set")
        require(row["completed"] == row["total_tasks"] == len(scene.tasks), "Task count mismatch")
        close(row["completion_rate"], 1.0, "completion_rate")
        require(row["time"] >= row["makespan"], "Return completion precedes unload")
        require(row["moves"] == row["empty_moves"] + row["loaded_moves"], "Move split mismatch")
        require(row["runtime_seconds"] > 0, "Invalid elapsed time")
        for field, numerator, denominator in (
            ("normalized_time", "makespan", "time"),
            ("normalized_response", "mean_flow_time", "response"),
            ("normalized_distance", "moves", "distance"),
        ):
            close(row[field], row[numerator] / context[denominator], field)
        score = (
            0.5 * row["normalized_time"]
            + 0.3 * row["normalized_response"]
            + 0.2 * row["normalized_distance"]
        )
        close(row["weighted_score"], score, "weighted_score")
        if solver == "baseline":
            close(row["makespan"], context["time"], "baseline time")
            close(row["mean_flow_time"], context["response"], "baseline response")
            close(row["moves"], context["distance"], "baseline distance")
            close(row["weighted_score"], 1.0, "baseline score")
    rebuilt = independent_summary(rows, manifest)
    published = read_json(root / "summary.json")
    require(len(rebuilt) == len(published), "Missing summary rows")
    for actual, expected_summary in zip(published, rebuilt):
        require(actual.keys() == expected_summary.keys(), "Summary schema mismatch")
        for key, value in expected_summary.items():
            if isinstance(value, str):
                require(actual[key] == value, "Summary identity mismatch")
            else:
                close(actual[key], value, "summary." + key)
    trace_checks = []
    expected_trace_names = {
        f"{name}-{solver}.json"
        for name in manifest["configs"]
        for solver in ("baseline", "sipp_budget")
    }
    paths = sorted((root / "traces").glob("*.json"))
    require({p.name for p in paths} == expected_trace_names, "Missing representative traces")
    for path in paths:
        entry = read_json(path)
        scene = unpack_scene(entry)
        result = entry["result"]
        validate(scene, result)
        name, solver = path.stem.rsplit("-", 1)
        require(scenario_id(scene) == scenario_id(scenes[name, 0][0]), "Trace scene mismatch")
        row = by_key[name, 0, solver]
        for field in (
            row.keys()
            - set(TEXT_FIELDS)
            - {
                "seed",
                "runtime_seconds",
                "replan_calls",
                "accepted_replans",
            }
        ):
            if type(row[field]) is bool:
                require(result[field] is row[field], "Trace boolean mismatch: " + field)
            else:
                close(result[field], row[field], "trace." + field)
        require(
            len(result["replanning_events"]) == row["accepted_replans"],
            "Trace replan count mismatch",
        )
        require(
            (result.get("algorithm") or {}).get("replan_calls", 0) == row["replan_calls"],
            "Trace replan invocation count mismatch",
        )
        trace_checks.append({"file": path.name, "sha256": digest(path), "valid": True})
    example = read_json(example_path)
    scene = unpack_scene(example)
    require(scene.is_v4 and scene.horizon == 600, "Example must support bounded web import")
    regenerated = generate(**example["config"])
    require(scenario_id(scene) == scenario_id(regenerated), "Example generator identity changed")
    require("result" not in example, "Input example should not embed a measured run")
    example_reference = reference_context(scene)
    require(example_reference["available"], "Example baseline execution did not complete")
    require(manifest["source_hashes"] == source_hashes(), "Source changed during the audit")
    return {
        "format": "agv-v4-evidence-audit-v1",
        "evidence_files_sha256": {
            name: digest(root / name) for name in ("manifest.json", "runs.csv", "summary.json")
        },
        "measurement_sources_match_current": True,
        "source_files_checked": len(manifest["source_hashes"]),
        "csv_rows_checked": len(rows),
        "scene_identities_checked": len(scenes),
        "fixed_references_reproduced": len(scenes),
        "normalized_scores_recomputed": len(rows),
        "baseline_unit_scores_checked": len(scenes),
        "summary_rows_independently_rebuilt": len(rebuilt),
        "representative_execution_traces": trace_checks,
        "example": {
            "file": str(example_path.relative_to(ROOT)),
            "scenario_sha256": scenario_id(scene),
            "tasks": len(scene.tasks),
            "vehicles": len(scene.homes),
            "horizon": scene.horizon,
            "roundtrip_and_generator_match": True,
            "independently_validated_reference_completion": True,
            "reference_costs": {
                key: example_reference[key] for key in ("time", "response", "distance")
            },
        },
        "paired_score_effects": [
            {
                "scenario": row["scenario"],
                "solver": row["solver"],
                "mean_score": row["weighted_score_mean"],
                "improvement_pct": row["weighted_score_improvement_pct"],
                "wins": row["score_wins"],
                "pairs": row["paired_successes"],
            }
            for row in rebuilt
            if row["solver"] != "baseline"
        ],
        "scope": (
            "This audit checks all saved CSV identities and calculations and replays the "
            "independent validator on six saved execution traces. It reproduces 18 fixed "
            "benchmark reference runs and one example reference; it does not rerun all "
            "54 timed candidate experiments or unit "
            "tests. The benchmark itself validated all 54 executions before writing them. "
            "Six paired seeds per template and one wall-clock repetition are exploratory; "
            "the results do not establish global optimality or general superiority."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/v4")
    parser.add_argument(
        "--example", type=Path, default=ROOT / "examples/scenarios/v4_small_dynamic.json"
    )
    parser.add_argument("--source-dir", type=Path, help="Optional original V4 folder to hash")
    parser.add_argument("--report-pdf", type=Path, help="Optional inspiration PDF to hash")
    parser.add_argument("--test-log", type=Path, help="Optional prior unittest log to summarize")
    parser.add_argument("--output", type=Path, help="Write the JSON audit to this path")
    args = parser.parse_args()
    report = audit(args.results.resolve(), args.example.resolve())
    provenance = {}
    if args.source_dir:
        base = args.source_dir.resolve()
        require(base.is_dir(), "Missing original V4 folder")
        files = {
            str(path.relative_to(base)): digest(path)
            for path in sorted(base.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and not path.name.startswith(".")
        }
        provenance["teammate_delivery"] = {"name": base.name, "files_sha256": files}
    if args.report_pdf:
        provenance["inspiration_pdf"] = {
            "name": args.report_pdf.name,
            "sha256": digest(args.report_pdf),
            "role": "Source material for review; no instructions or PDF contents imported",
        }
    if args.test_log:
        log = args.test_log.read_text(encoding="utf-8")
        matches = re.findall(r"Ran (\d+) tests in ([\d.]+)s\s+OK\s*$", log)
        require(len(matches) == 1, "Test log does not end with a successful unittest run")
        count, elapsed = matches[0]
        provenance["prior_unittest_run"] = {
            "log_name": args.test_log.name,
            "log_sha256": digest(args.test_log),
            "tests": int(count),
            "elapsed_seconds": float(elapsed),
            "status": "passed",
            "attribution": "Prior reviewer-supplied test log; tests are not rerun by this audit",
        }
    if provenance:
        report["input_provenance"] = provenance
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
