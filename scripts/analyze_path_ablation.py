"""Paired component effects and the pre-specified simplified order-only profile."""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from analyze_joint_study import analyze
from report_joint_holdout import effects


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--primary", required=True, type=Path)
    p.add_argument("--ablation", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    rows = [
        json.loads(x)
        for d in (a.primary, a.ablation)
        for x in (d / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if not all(r["valid"] for r in rows):
        raise ValueError("Invalid data cannot enter a component-effect comparison")
    keys = [(r["map"], r["mode"], r["seed"], r["variant"], r["optimizer_seed"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate actual executions")
    freezes = [
        json.loads((d / "freeze.json").read_text(encoding="utf-8")) for d in (a.primary, a.ablation)
    ]
    if freezes[0]["source_sha256"] != freezes[1]["source_sha256"]:
        raise ValueError("Different physical algorithm sources")
    for r in rows:
        if r["variant"] != "aco__sipp":
            continue
        name = f"{r['map']}-dynamic-{r['seed']}"
        ablation_scene = a.ablation / "scenes" / (name + ".json")
        if not ablation_scene.exists():
            ablation_scene = a.ablation / "scenes" / (name + f"-{r['optimizer_seed']}.json")
        if json.loads(ablation_scene.read_text(encoding="utf-8")) != json.loads(
            (a.primary / "scenes" / (name + ".json")).read_text(encoding="utf-8")
        ):
            raise ValueError("Ablation scene differs from primary scene")
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "rows.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (a.output / "freeze.json").write_text(
        json.dumps(
            dict(
                derived_data_only=True,
                parents=[str(a.primary), str(a.ablation)],
                source_sha256=freezes[0]["source_sha256"],
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    with (a.output / "runs.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)
    selection = dict(static="assignment__sipp", dynamic="aco__sipp")
    info = analyze(a.output, "portfolio__sipp", selection)
    assignment = analyze(a.output, "assignment__sipp", selection)
    (a.output / "analysis-simplified.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    (a.output / "analysis-simplified-vs-assignment.json").write_text(
        json.dumps(assignment, indent=2), encoding="utf-8"
    )
    groups = defaultdict(list)
    for r in rows:
        groups[r["map"], r["mode"], r["seed"], r["variant"]].append(r)
    cases = sorted({k[:3] for k in groups if k[1] == "dynamic"})
    summary = dict(
        actual_parent_runs=len(rows),
        distinct_scenes=len({k[:3] for k in groups}),
        same_sources=True,
        same_scenes=True,
        secondary_selection=selection,
        comparisons={},
    )
    for label, new, old in (
        ("route_addition_vs_aco_sipp", "aco__aco_sipp", "aco__sipp"),
        ("aco_dispatch_vs_assignment", "aco__sipp", "assignment__sipp"),
    ):
        pairs = []
        for c in cases:
            x, b = groups[(*c, new)], groups[(*c, old)]
            pairs.append(
                dict(
                    map=c[0],
                    mode=c[1],
                    seed=c[2],
                    gain_pct=100 * (1 - mean(r["F"] for r in x) / mean(r["F"] for r in b)),
                    cpu_ratio=mean(r["cpu_seconds"] for r in x) / mean(r["cpu_seconds"] for r in b),
                )
            )
        summary["comparisons"][label] = dict(**effects(pairs), pairs=pairs)
    for label, data in (
        ("simplified_profile_vs_portfolio", info),
        ("simplified_profile_vs_assignment", assignment),
    ):
        item = data["variants"]["selected_profile"]
        summary["comparisons"][label] = dict(
            **effects(item["pairs"]),
            means=item["means"],
            baseline_means=item["baseline_means"],
            contributions=item["contributions"],
            by_mode={
                mode: effects([x for x in item["pairs"] if x["mode"] == mode])
                for mode in ("static", "dynamic")
            },
        )
    (a.output / "ablation-report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: {
                    key: value
                    for key, value in d.items()
                    if key not in ("pairs", "means", "baseline_means", "contributions", "by_mode")
                }
                for k, d in summary["comparisons"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
