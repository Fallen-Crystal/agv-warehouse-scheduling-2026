#!/usr/bin/env python3
"""Explain paired mechanism effects without changing the fixed objective."""

import argparse
import json
import random
import statistics
from pathlib import Path

from agv.experiments.v91_bench import read_rows
from agv.io.storage import write_json


def analyze(directory):
    root = Path(directory)
    rows = read_rows(root / "runs.csv")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    comparisons = (
        ("G0", "G1"),
        ("G0", "G2"),
        ("G0", "G3"),
        ("G2", "G3"),
        ("G3", "G4"),
        ("G0", "G4"),
        ("G0", "B0"),
        ("B0", "B1"),
        ("G0", "B1"),
    )
    effects = []
    for base, candidate in comparisons:
        for workload in ("__all__", "dense_static", "sparse_uniform", "shared_bursts"):
            pairs = []
            for key, row in index.items():
                if row["solver"] != candidate or (
                    workload != "__all__" and row["workload"] != workload
                ):
                    continue
                other = index.get((key[0], key[1], base))
                if other is not None and row["comparison_valid"] and other["comparison_valid"]:
                    if row["scenario_sha256"] != other["scenario_sha256"]:
                        raise ValueError("Mismatched paired scenes")
                    pairs.append((other, row))
            if not pairs:
                continue
            gains = [100 * (1 - b["weighted_score"] / a["weighted_score"]) for a, b in pairs]
            parts = {name: [] for name in ("T", "R", "D")}
            for a, b in pairs:
                for name, metric, weight in (
                    ("T", "makespan", 0.5),
                    ("R", "mean_flow_time", 0.3),
                    ("D", "moves", 0.2),
                ):
                    parts[name].append(
                        100
                        * weight
                        * (a[metric] - b[metric])
                        / a["reference_" + name]
                        / a["weighted_score"]
                    )
            rng = random.Random(20261017)
            boot = sorted(statistics.mean(rng.choices(gains, k=len(gains))) for _ in range(4000))
            record = dict(
                base=base,
                candidate=candidate,
                workload=workload,
                pairs=len(pairs),
                F_gain_pct=statistics.mean(gains),
                F_gain_pct_95ci=[boot[99], boot[3900]],
                F_component_contributions_pct={
                    name: statistics.mean(values) for name, values in parts.items()
                },
                wins=sum(g > 1e-10 for g in gains),
                losses=sum(g < -1e-10 for g in gains),
                ties=sum(abs(g) <= 1e-10 for g in gains),
                p90_worse=sum(b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs),
                max_response_worse=sum(b["max_flow_time"] > a["max_flow_time"] for a, b in pairs),
                cpu_ratio_mean=statistics.mean(
                    b["cpu_seconds"] / a["cpu_seconds"] for a, b in pairs
                ),
            )
            for metric in (
                "makespan",
                "mean_flow_time",
                "moves",
                "empty_moves",
                "traffic_wait_steps",
                "standby_steps",
            ):
                record[metric + "_absolute_delta_mean"] = statistics.mean(
                    b[metric] - a[metric] for a, b in pairs
                )
            if (
                abs(sum(record["F_component_contributions_pct"].values()) - record["F_gain_pct"])
                > 1e-9
            ):
                raise ValueError("Weighted effect components do not add up")
            effects.append(record)
    baseline = [r for r in rows if r["solver"] == "G0" and r["comparison_valid"]]
    gaps = {
        key: statistics.mean(r[key] for r in baseline if r[key] is not None)
        for key in ("T_gap_pct", "R_gap_pct", "D_gap_pct", "F_gap_pct")
    }
    return dict(
        schema="agv-v91-mechanism-analysis-v1",
        source=str(root.name),
        uncertainty="Fixed-template paired bootstrap, descriptive CPU, no correction for development selection",
        baseline_mean_relaxation_gaps=gaps,
        comparisons=effects,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_json(args.output, analyze(args.input))
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False))
