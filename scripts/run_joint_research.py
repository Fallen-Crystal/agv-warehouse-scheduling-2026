"""Run one optional joint-dispatch experiment and export a replayable result."""

import argparse
import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.runner.joint_research import run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input")
    p.add_argument("--output", required=True)
    p.add_argument(
        "--method",
        choices=("assignment", "priority", "combined", "random", "aco", "pso"),
        default="assignment",
    )
    p.add_argument("--seed", type=int, default=18100)
    p.add_argument("--optimizer-seed", type=int, default=0)
    p.add_argument("--candidate-budget", type=int, default=8)
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("Choose a new output path")
    if a.input:
        data = json.loads(Path(a.input).read_text(encoding="utf-8"))
        scene = Scenario.from_dict(data.get("scene", data.get("scenario", data)))
    else:
        scene = generate_current(
            size="medium",
            seed=a.seed,
            vehicles=4,
            task_count=12,
            shelf_layers=8,
            mode="static",
            horizon=None,
        )
    result = score_result(
        scene,
        run(
            scene,
            mode=a.method,
            optimizer_seed=a.optimizer_seed,
            candidate_budget=a.candidate_budget,
        ),
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
