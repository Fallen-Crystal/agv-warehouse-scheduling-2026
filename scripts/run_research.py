"""Run the optional GA/priority research solver without changing public defaults."""

import argparse
import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.planning.order_search import exact_single
from agv.runner.research import run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input")
    p.add_argument("--output", required=True)
    p.add_argument("--size", choices=("medium", "large", "xlarge", "xxlarge"), default="medium")
    p.add_argument("--vehicles", type=int, default=4)
    p.add_argument("--tasks", type=int, default=12)
    p.add_argument("--layers", type=int, default=8)
    p.add_argument("--mode", choices=("static", "dynamic"), default="static")
    p.add_argument("--seed", type=int, default=60)
    p.add_argument("--search", choices=("greedy", "ga", "exact"), default="ga")
    p.add_argument("--coordinate", action="store_true")
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("Output already exists; choose a new output path")
    if a.input:
        data = json.loads(Path(a.input).read_text(encoding="utf-8"))
        scene = Scenario.from_dict(data.get("scene", data.get("scenario", data)))
    else:
        scene = generate_current(
            size=a.size,
            vehicles=a.vehicles,
            task_count=a.tasks,
            shelf_layers=a.layers,
            mode=a.mode,
            seed=a.seed,
            horizon=None,
        )
    certificate = exact_single(scene) if a.search == "exact" else None
    result = score_result(scene, run(scene, mode=a.search, coordinate=a.coordinate))
    if not result["score_valid"]:
        raise RuntimeError("Execution failed independent validation/scoring")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as f:
        json.dump(
            dict(scene=scene.to_dict(), result=result, certificate=certificate),
            f,
            ensure_ascii=False,
        )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "weighted_score",
                    "makespan",
                    "mean_flow_time",
                    "moves",
                    "estimated_energy",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
