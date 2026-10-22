"""Audit a frozen selected profile, paired effects, and offline lower-bound gaps."""

import argparse
import hashlib
import json
import random
from pathlib import Path
from statistics import mean

from analyze_joint_study import analyze

from agv.evaluation.bounds import lower_bounds
from agv.evaluation.objective import reference_context
from agv.experiments.search_benchmark import fingerprints
from agv.warehouse.scenarios import Scenario


def effects(pairs):
    seeds = sorted({p["seed"] for p in pairs})
    clusters = [mean(p["gain_pct"] for p in pairs if p["seed"] == s) for s in seeds]
    rng = random.Random(20261022)
    samples = sorted(mean(rng.choices(clusters, k=len(clusters))) for _ in range(20000))
    return dict(
        cases=len(pairs),
        mean_gain_pct=mean(p["gain_pct"] for p in pairs),
        cluster_ci95=[samples[499], samples[19499]],
        seed_clusters=len(seeds),
        wins=sum(p["gain_pct"] > 1e-9 for p in pairs),
        losses=sum(p["gain_pct"] < -1e-9 for p in pairs),
        ties=sum(abs(p["gain_pct"]) <= 1e-9 for p in pairs),
        mean_cpu_ratio=mean(p["cpu_ratio"] for p in pairs),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--selection", required=True, type=Path)
    a = p.parse_args()
    selection = json.loads(a.selection.read_text(encoding="utf-8"))
    freeze = json.loads((a.directory / "freeze.json").read_text(encoding="utf-8"))
    if freeze["source_sha256"] != fingerprints():
        raise ValueError("Current source differs from frozen confirmation source")
    original = analyze(a.directory, "portfolio__sipp", selection)
    assignment = analyze(a.directory, "assignment__sipp", selection)
    (a.directory / "analysis.json").write_text(json.dumps(original, indent=2), encoding="utf-8")
    (a.directory / "analysis-vs-assignment.json").write_text(
        json.dumps(assignment, indent=2), encoding="utf-8"
    )
    rows = [
        json.loads(x) for x in (a.directory / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = dict(
        actual_runs=len(rows),
        valid=sum(r["valid"] for r in rows),
        selection=dict(static=selection["static"], dynamic=selection["dynamic"]),
        selection_sha256=hashlib.sha256(a.selection.read_bytes()).hexdigest(),
        source_unchanged=True,
        derived_profile_rows=original["derived_profile_rows"],
        comparisons={},
    )
    for label, analysis, variant in (
        ("profile_vs_portfolio", original, "selected_profile"),
        ("profile_vs_assignment", assignment, "selected_profile"),
        ("assignment_vs_portfolio", original, "assignment__sipp"),
    ):
        info = analysis["variants"][variant]
        summary["comparisons"][label] = dict(
            overall=effects(info["pairs"]),
            by_mode={
                mode: effects([x for x in info["pairs"] if x["mode"] == mode])
                for mode in ("static", "dynamic")
            },
            means=info["means"],
            baseline_means=info["baseline_means"],
            contributions=info["contributions"],
            worst_cases=sorted(info["pairs"], key=lambda x: x["gain_pct"])[:8],
        )
    bounds = []
    for path in sorted((a.directory / "scenes").glob("*.json")):
        scene = Scenario.from_dict(json.loads(path.read_text(encoding="utf-8")))
        b, context = lower_bounds(scene), reference_context(scene)
        lower = (
            0.5 * b["T"] / context["time"]
            + 0.3 * b["R"] / context["response"]
            + 0.2 * b["D"] / context["distance"]
        )
        size, mode, seed = path.stem.split("-")
        selected = [
            r
            for r in rows
            if (r["map"], r["mode"], r["seed"], r["variant"])
            == (size, mode, int(seed), selection[mode])
        ]
        actual = mean(r["F"] for r in selected)
        if actual < lower - 1e-10:
            raise ValueError("Selected execution violates a proven offline lower bound")
        bounds.append(
            dict(
                case=path.stem,
                lower_F=lower,
                F=actual,
                conservative_gap_upper_pct=100 * (actual / lower - 1),
            )
        )
    summary["offline_bound_diagnostics"] = dict(
        note="Relaxed lower bounds are not attainable optima; gap is only a conservative upper bound on relative suboptimality",
        mean_gap_upper_pct=mean(x["conservative_gap_upper_pct"] for x in bounds),
        cases=bounds,
    )
    (a.directory / "profile-report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v["overall"] for k, v in summary["comparisons"].items()}, indent=2))


if __name__ == "__main__":
    main()
