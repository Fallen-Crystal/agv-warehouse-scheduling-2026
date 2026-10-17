#!/usr/bin/env python3
"""Plot paired V9.1 effects; requires the optional .[plots] dependency."""

import argparse
import json
from pathlib import Path


def plot(source, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = json.loads(Path(source).read_text(encoding="utf-8"))
    index = {(r["candidate"], r["workload"]): r for r in report["comparisons"] if r["base"] == "G0"}
    policies = ("G4", "B0", "B1")
    labels = ("Position + ETA + delay", "Stream BCRD", "BCRD + visible P90 guard")
    workloads = ("__all__", "dense_static", "sparse_uniform", "shared_bursts")
    titles = ("All paired scenes", "Dense static", "Sparse uniform", "Shared D bursts")
    colors = ("#1565a8", "#b66426", "#37835f")
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), sharey=True, layout="constrained")
    for axis, workload, title in zip(axes, workloads, titles):
        for y, (policy, color) in enumerate(zip(policies, colors)):
            row = index[policy, workload]
            value = row["F_gain_pct"]
            low, high = row["F_gain_pct_95ci"]
            axis.errorbar(
                value, y, xerr=[[value - low], [high - value]], fmt="o", color=color, capsize=4
            )
        axis.axvline(0, color="#65717c", lw=0.9, ls="--")
        axis.set_title(f"{title} (n={index['G4', workload]['pairs']})", fontsize=10)
        axis.set_xlabel("F improvement (%)")
        axis.grid(axis="x", color="#e4e8ed")
    axes[0].set_yticks(range(3), labels)
    axes[0].invert_yaxis()
    fig.suptitle("Frozen V9.1 holdout: mean paired gain and 95% bootstrap interval", fontsize=12)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    fig.savefig(
        destination,
        dpi=180,
        metadata={
            "Description": "Positive values indicate lower F than G0. Fixed synthetic templates; no unseen-map guarantee."
        },
    )
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot(args.input, args.output)
