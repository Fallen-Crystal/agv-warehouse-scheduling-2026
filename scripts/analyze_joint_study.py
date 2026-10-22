"""Paired scene-level gains; confidence intervals cluster by environment seed."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean


def analyze(directory, baseline="portfolio", selection=None):
    rows = [
        json.loads(line)
        for line in (directory / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if not all(r["valid"] for r in rows):
        raise ValueError("Invalid rows must be resolved or reported before aggregate selection")
    actual_runs = len(rows)
    if selection is not None:
        rows += [
            dict(r, variant="selected_profile")
            for r in rows
            if r["variant"] == selection[r["mode"]]
        ]
    groups = defaultdict(list)
    for r in rows:
        groups[r["map"], r["mode"], r["seed"], r["variant"]].append(r)
    cases = {key[:3] for key in groups}
    variants = sorted({r["variant"] for r in rows} - {baseline})
    result = {}
    for variant in variants:
        pairs = []
        for c in sorted(cases):
            if (*c, variant) not in groups or (*c, baseline) not in groups:
                continue
            b = groups[(*c, baseline)]
            a = groups[(*c, variant)]
            baseF = mean(r["F"] for r in b)
            newF = mean(r["F"] for r in a)
            contributions = {
                name: 100 * w * (mean(r[key] for r in b) - mean(r[key] for r in a)) / baseF
                for name, key, w in (("T", "nt", 0.5), ("R", "nr", 0.3), ("D", "nd", 0.2))
            }
            pairs.append(
                dict(
                    map=c[0],
                    mode=c[1],
                    seed=c[2],
                    gain_pct=100 * (1 - newF / baseF),
                    baseline_F=baseF,
                    F=newF,
                    cpu_ratio=mean(r["cpu_seconds"] for r in a) / mean(r["cpu_seconds"] for r in b),
                    contributions=contributions,
                )
            )
        clusters = defaultdict(list)
        for p in pairs:
            clusters[p["seed"]].append(p["gain_pct"])
        seed_means = [mean(x) for x in clusters.values()]
        rng = random.Random(20261022)
        samples = sorted(mean(rng.choices(seed_means, k=len(seed_means))) for _ in range(20000))
        matched = [r for r in rows if r["variant"] == variant]
        breakdown = {}
        for m, mode in sorted({(p["map"], p["mode"]) for p in pairs}):
            breakdown[f"{m}/{mode}"] = mean(
                p["gain_pct"] for p in pairs if (p["map"], p["mode"]) == (m, mode)
            )
        result[variant] = dict(
            cases=len(pairs),
            gain_pct=mean(p["gain_pct"] for p in pairs),
            cluster_ci95=[samples[499], samples[19499]],
            seed_clusters=len(clusters),
            wins=sum(p["gain_pct"] > 1e-9 for p in pairs),
            losses=sum(p["gain_pct"] < -1e-9 for p in pairs),
            ties=sum(abs(p["gain_pct"]) <= 1e-9 for p in pairs),
            cpu_ratio=mean(p["cpu_ratio"] for p in pairs),
            contributions={k: mean(p["contributions"][k] for p in pairs) for k in ("T", "R", "D")},
            means={
                k: mean(r[k] for r in matched)
                for k in (
                    "F",
                    "T",
                    "R",
                    "D",
                    "p90",
                    "cpu_seconds",
                    "anchor_previews",
                    "additional_previews",
                )
            },
            baseline_means={
                k: mean(
                    r[k]
                    for r in rows
                    if r["variant"] == baseline
                    and (r["map"], r["mode"], r["seed"])
                    in {(p["map"], p["mode"], p["seed"]) for p in pairs}
                )
                for k in ("F", "T", "R", "D", "p90", "cpu_seconds")
            },
            breakdown=breakdown,
            pairs=pairs,
        )
    return dict(
        runs=actual_runs,
        valid=actual_runs,
        derived_profile_rows=len(rows) - actual_runs,
        baseline=baseline,
        variants=result,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--baseline", default="portfolio")
    parser.add_argument("--selection")
    parser.add_argument("--output", default="analysis.json")
    args = parser.parse_args()
    selection = (
        json.loads(Path(args.selection).read_text(encoding="utf-8")) if args.selection else None
    )
    result = analyze(args.directory, args.baseline, selection)
    (args.directory / args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: {
                    x: v[x]
                    for x in (
                        "cases",
                        "gain_pct",
                        "cluster_ci95",
                        "wins",
                        "losses",
                        "ties",
                        "cpu_ratio",
                    )
                }
                for k, v in result["variants"].items()
            },
            indent=2,
        )
    )
