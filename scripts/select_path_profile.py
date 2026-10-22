"""Freeze separate static/dynamic choices from the completed development set."""

import argparse
import json
from pathlib import Path
from statistics import mean


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("analysis", type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    d = json.loads(a.analysis.read_text(encoding="utf-8"))
    if d["runs"] != 180 or d["valid"] != 180:
        raise ValueError("Require the entire frozen development matrix")
    route_order = ["sipp", "astar", "aco_sipp", "pso_sipp", "aco_astar", "pso_astar"]
    order_order = ["portfolio", "assignment", "aco"]
    selection, rankings = {}, {}
    for mode in ("static", "dynamic"):
        values = [(0.0, "portfolio__sipp")]
        for variant, info in d["variants"].items():
            pairs = [p for p in info["pairs"] if p["mode"] == mode]
            if pairs:
                values.append((mean(p["gain_pct"] for p in pairs), variant))
        best_gain = max(x[0] for x in values)
        tied = [x for x in values if abs(x[0] - best_gain) <= 1e-10]
        selected = min(
            tied,
            key=lambda x: (
                route_order.index(x[1].split("__")[1]),
                order_order.index(x[1].split("__")[0]),
            ),
        )
        selection[mode] = selected[1]
        rankings[mode] = sorted(values, reverse=True)
    selection.update(
        rule="maximum development mean paired F gain; ties prefer simpler routing then simpler order search",
        development_analysis=str(a.analysis),
        rankings=rankings,
        confirmation_seeds=list(range(18100, 18106)),
        optimizer_seed=0,
    )
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(selection, f, indent=2)
    print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
