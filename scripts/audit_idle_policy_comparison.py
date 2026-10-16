"""Recompute paired CSV effects and independently audit saved trajectories."""

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from agv.domain import Scenario
from agv.evaluation.validation import validate
from agv.io.scenes import scenario_id

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(folder, summary_only=False):
    rows = list(csv.DictReader((folder / "runs.csv").open(encoding="utf-8-sig")))
    protocol = read(folder / "protocol.json")
    if len(rows) != protocol["runs"]:
        raise ValueError("Missing raw run rows")
    groups = defaultdict(dict)
    traces = 0
    for row in rows:
        case, policy = row["case"], row["policy"]
        if policy in groups[case]:
            raise ValueError("Duplicate case/policy")
        groups[case][policy] = row
        if row["feasible"] != "True" or row["cutoff"] != "False":
            raise ValueError("Saved study includes failed or cutoff execution")
        base = folder / "selected" if summary_only else folder / "traces"
        trace_path = base / f"{case}_{policy}.json"
        input_path = (
            folder / "selected" / f"{case}_input.json"
            if summary_only
            else folder / "inputs" / f"{case}.json"
        )
        if summary_only and not trace_path.exists():
            continue
        scene = Scenario.from_dict(read(input_path))
        result = read(trace_path)
        validate(scene, result)
        if row["scenario_sha256"] != scenario_id(scene):
            raise ValueError("Input identity differs")
        for field in (
            "makespan",
            "mean_flow_time",
            "moves",
            "empty_moves",
            "loaded_moves",
            "time",
            "standby_steps",
        ):
            if not math.isclose(float(row[field]), result[field]):
                raise ValueError("CSV differs from independently audited trace: " + field)
        if not math.isclose(float(row["energy"]), 0.05 * result["moves"]):
            raise ValueError("Wrong energy proxy")
        traces += 1
    if len(groups) != protocol["cases"]:
        raise ValueError("Missing paired case")
    scores = {}
    for case, policies in groups.items():
        if set(policies) != {"near_delivery", "return_interruptible"}:
            raise ValueError("Missing paired policy")
        a, b = policies["near_delivery"], policies["return_interruptible"]
        if a["scenario_sha256"] != b["scenario_sha256"]:
            raise ValueError("Paired inputs differ")
        scores[case] = (
            0.5 * float(a["makespan"]) / float(b["makespan"])
            + 0.3 * float(a["mean_flow_time"]) / float(b["mean_flow_time"])
            + 0.2 * float(a["moves"]) / float(b["moves"])
        )
    paired_path = folder / "paired_effects.csv"
    if paired_path.exists():
        paired = list(csv.DictReader(paired_path.open(encoding="utf-8-sig")))
        if len(paired) != len(scores) or len({p["case"] for p in paired}) != len(scores):
            raise ValueError("Missing or duplicate paired effects")
        for p in paired:
            if not math.isclose(float(p["F_A"]), scores[p["case"]], abs_tol=1e-12):
                raise ValueError("Wrong fixed-reference score")
    summary_path = folder / "summary.json"
    if summary_path.exists():
        summary = read(summary_path)["overall"]
        if summary["n"] != len(scores) or not math.isclose(
            summary["F"]["mean_improvement_pct"],
            statistics.mean(100 * (1 - x) for x in scores.values()),
            abs_tol=1e-10,
        ):
            raise ValueError("Wrong summary")
    snapshot = folder / "compare_idle_policies.py"
    if (
        snapshot.exists()
        and hashlib.sha256(snapshot.read_bytes()).hexdigest() != protocol["script_sha256"]
    ):
        raise ValueError("Frozen experiment script changed")
    normalized = folder / "source-lf-sha256.json"
    if normalized.exists():
        for name, digest in read(normalized).items():
            if (
                hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                != digest
            ):
                raise ValueError("Production source differs from saved study")
    if not summary_only and traces != len(rows):
        raise ValueError("Full audit did not read every trace")
    return dict(
        pairs=len(groups),
        raw_runs=len(rows),
        traces_independently_audited=traces,
        scope="compact summaries and selected traces" if summary_only else "all traces",
        mean_F_improvement_pct=statistics.mean(100 * (1 - x) for x in scores.values()),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "runs/idle-policy-study")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit(args.input, args.summary_only), indent=2))


if __name__ == "__main__":
    main()
