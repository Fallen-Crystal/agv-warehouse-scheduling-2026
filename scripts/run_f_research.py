"""Optional fixed-F dispatch study; original defaults and evaluator remain intact."""

import argparse
import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.runner.f_research import run
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
    p.add_argument("--seed", type=int, default=6100)
    p.add_argument(
        "--method", choices=("matching", "ga", "random", "hybrid", "portfolio"), default="ga"
    )
    p.add_argument("--terms", choices=("T", "R", "D", "TR", "TD", "RD", "TRD"), default="TRD")
    p.add_argument("--optimizer-seed", type=int, default=0)
    p.add_argument("--budget", type=int, default=192)
    p.add_argument("--greedy-matching", action="store_true")
    p.add_argument("--uncalibrated", action="store_true")
    a = p.parse_args()
    target = Path(a.output)
    if target.exists():
        p.error("Output already exists; choose another path")
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
    result = score_result(
        scene,
        run(
            scene,
            method=a.method,
            terms=a.terms,
            matching=not a.greedy_matching,
            calibrated=not a.uncalibrated,
            budget=a.budget,
            optimizer_seed=a.optimizer_seed,
        ),
    )
    if not result["score_valid"]:
        raise RuntimeError("No independently valid complete score")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as f:
        json.dump(dict(scene=scene.to_dict(), result=result), f, ensure_ascii=False)
    print(
        json.dumps(
            {k: result[k] for k in ("weighted_score", "makespan", "mean_flow_time", "moves")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
