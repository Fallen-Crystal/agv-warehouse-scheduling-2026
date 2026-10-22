"""Replay optional order/path combinations; regime is an explicit known setting."""

import argparse
import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.runner.path_research import ROUTES, run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input")
    p.add_argument("--output", required=True)
    p.add_argument("--route", choices=ROUTES, default="sipp")
    p.add_argument(
        "--orders",
        choices=(
            "portfolio",
            "assignment",
            "aco",
            "pso",
            "combined",
            "priority",
            "random",
            "greedy",
        ),
        default="assignment",
    )
    p.add_argument("--selection", help="Frozen development configuration; requires explicit regime")
    p.add_argument("--regime", choices=("static", "dynamic"))
    p.add_argument("--seed", type=int, default=18100)
    p.add_argument("--optimizer-seed", type=int, default=0)
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("Choose a new output path")
    if a.selection:
        if not a.regime:
            p.error("Specify the known --regime when using --selection")
        selection = json.loads(Path(a.selection).read_text(encoding="utf-8"))
        a.orders, a.route = selection[a.regime].split("__")
    if a.input:
        data = json.loads(Path(a.input).read_text(encoding="utf-8"))
        scene = Scenario.from_dict(data.get("scene", data.get("scenario", data)))
    else:
        scene = generate_current(
            size="medium",
            seed=a.seed,
            vehicles=4,
            task_count=12 if a.regime != "dynamic" else 8,
            shelf_layers=8,
            mode=a.regime or "static",
            arrival="burst",
            horizon=None,
        )
    result = score_result(
        scene, run(scene, route=a.route, orders=a.orders, optimizer_seed=a.optimizer_seed)
    )
    validate(scene, result)
    if not result["score_valid"]:
        raise RuntimeError("No independently valid complete score")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as f:
        json.dump(dict(scene=scene.to_dict(), result=result), f, ensure_ascii=False)
    print(
        json.dumps(
            {k: result[k] for k in ("weighted_score", "makespan", "mean_flow_time", "moves")}
        )
    )


if __name__ == "__main__":
    main()
