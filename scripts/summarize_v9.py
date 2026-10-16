#!/usr/bin/env python3
"""Inspect V9 idle tradeoffs from frozen rows and first-seed retained traces.

Percentage effects are paired per-instance means, not ratios of pooled costs.
Neighborhood occupancy is descriptive and only covers retained traces; it is
neither a queue estimator nor a causal attribution of all traffic delay.
"""

import argparse
import json
import statistics
from pathlib import Path

from agv.experiments.bcrd import read_rows
from agv.io.scenes import unpack_scene


def effects(directory):
    directory = Path(directory)
    rows = read_rows(directory / "runs.csv")
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
    baseline = protocol.get("baseline", "G0")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    groups = []
    fields = (
        "weighted_score",
        "makespan",
        "mean_flow_time",
        "p90_flow_time",
        "moves",
        "empty_moves",
        "loaded_moves",
        "traffic_wait_steps",
    )
    for scenario in list(protocol["configs"]) + ["__all__"]:
        for solver in protocol["solvers"]:
            own = [
                r
                for r in rows
                if r["solver"] == solver and (scenario == "__all__" or r["scenario"] == scenario)
            ]
            pairs = [(index[r["scenario"], r["seed"], baseline], r) for r in own]
            pairs = [(a, b) for a, b in pairs if a["comparison_valid"] and b["comparison_valid"]]
            item = dict(
                scenario=scenario,
                solver=solver,
                runs=len(own),
                paired=len(pairs),
                excluded=len(own) - len(pairs),
                metrics={},
            )
            for field in fields:
                values = [(a[field], b[field]) for a, b in pairs]
                ratios = [100 * (a - b) / a for a, b in values if a > 0]
                item["metrics"][field] = dict(
                    baseline_mean=statistics.mean(a for a, _ in values) if values else None,
                    candidate_mean=statistics.mean(b for _, b in values) if values else None,
                    paired_improvement_pct_mean=statistics.mean(ratios) if ratios else None,
                    positive_baseline_denominator_pairs=len(ratios),
                    absolute_difference_mean=statistics.mean(b - a for a, b in values)
                    if values
                    else None,
                )
            item.update(
                final_time_difference_mean=statistics.mean(b["time"] - a["time"] for a, b in pairs)
                if pairs
                else None,
                standby_steps_mean=statistics.mean(b["standby_steps"] for _, b in pairs)
                if pairs
                else None,
                cpu_ratio_mean=statistics.mean(
                    b["cpu_seconds"] / a["cpu_seconds"] for a, b in pairs
                )
                if pairs
                else None,
                p90_degradations=sum(b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs),
                planning_attempt_failures=sum(r["planning_failures"] for r in own),
            )
            groups.append(item)
    occupancy = []
    for path in sorted((directory / "traces").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("experiment_audit", {}).get("execution_valid"):
            occupancy.append(
                dict(
                    trace=path.name,
                    omitted_reason="Not independently validated; no occupancy estimate",
                )
            )
            continue
        s, result = unpack_scene(data), data["result"]
        samples = stationary = standby = traffic = 0
        for trajectory, labels in zip(result["paths"], result["interval_states"]):
            for a, b, state in zip(trajectory, trajectory[1:], labels):
                distance = min(abs(a[0] - d[0]) + abs(a[1] - d[1]) for d in s.stations)
                if not 0 < distance <= 2:
                    continue
                samples += 1
                stationary += a == b
                standby += state == "standby"
                traffic += a == b and state in ("returning", "to_pickup", "to_delivery")
        occupancy.append(
            dict(
                trace=path.name,
                config=data["config"],
                neighborhood_position_samples=samples,
                stationary_samples=stationary,
                standby_samples=standby,
                traffic_wait_samples=traffic,
                radius=2,
                excludes_station_cell=True,
            )
        )
    return dict(
        schema="agv-v9-idle-effects-v1",
        groups=groups,
        retained_trace_neighborhood=occupancy,
        scope="Paired rows cover the complete matrix. Neighborhood samples cover preselected first-seed traces only; no queue-length or causal-delay claim.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = effects(args.directory)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(
        json.dumps(
            dict(groups=len(report["groups"]), traces=len(report["retained_trace_neighborhood"]))
        )
    )
