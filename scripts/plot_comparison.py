"""Optional: uv run --with matplotlib python scripts/plot_comparison.py."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    root = Path("results/v2")
    rows = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    names = [
        "static_small_wide",
        "static_small_bottleneck",
        "dynamic_medium_burst",
        "dynamic_large_shared",
        "dynamic_small_switching",
        "movingai_heldout",
    ]
    labels = [
        "Small wide",
        "Small bottleneck",
        "Burst orders",
        "Shared delivery",
        "Hotspot switch",
        "Public heldout",
    ]
    solvers = ["joint_only", "sipp_joint", "sipp_conflict", "sipp_budget", "sipp_learned"]
    styles = ["#8a8f98", "#b98a58", "#248b7a", "#657fc6", "#a86498"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), layout="constrained")
    for i, (solver, color) in enumerate(zip(solvers, styles)):
        own = [
            next(r for r in rows if r["scenario"] == name and r["solver"] == solver)
            for name in names
        ]
        old = [
            next(r for r in rows if r["scenario"] == name and r["solver"] == "joint_only")
            for name in names
        ]
        axes[0].plot(
            range(len(names)),
            [r["mean_flow_time_improvement_pct"] for r in own],
            marker="o",
            label=solver,
            color=color,
        )
        axes[1].bar(
            [j + (i - 2) * 0.15 for j in range(len(names))],
            [r["runtime_mean"] / a["runtime_mean"] for r, a in zip(own, old)],
            0.14,
            label=solver,
            color=color,
        )
    axes[0].set_ylabel("Mean flow time reduction vs original greedy (%)")
    axes[1].set_ylabel("Runtime / old joint planner runtime")
    for ax in axes:
        ax.set_xticks(range(len(names)), labels, rotation=22, ha="right")
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        ax.legend(fontsize=8)
    axes[0].set_title("Matched successful scenes; lower flow time is better")
    axes[1].set_title("Single-run per seed timing; lower is faster")
    axes[1].axhline(1, color="#888", linewidth=0.8)
    fig.savefig(root / "comparison.png", dpi=160)
    fig.savefig(root / "comparison.pdf")


if __name__ == "__main__":
    main()
