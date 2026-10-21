"""Read-only development measurement. Final stdout JSON is controller input."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.registry import run_named
from agv.runner.research import run
from agv.warehouse.mixed import generate_current


def measure():
    rows = []
    for vehicles, tasks, mode in [(1, 8, "static"), (4, 12, "static"), (4, 12, "dynamic")]:
        for seed in (60, 61):
            s = generate_current(
                seed=seed, task_count=tasks, vehicles=vehicles, mode=mode, horizon=None
            )
            baseline = run_named("sipp_stream_dispatch", s)
            result = score_result(s, run(s))
            validate(s, result)
            if not result["score_valid"]:
                raise ValueError("Invalid candidate execution")
            row = dict(
                seed=seed,
                vehicles=vehicles,
                mode=mode,
                baseline=baseline["weighted_score"],
                candidate=result["weighted_score"],
                T=result["makespan"],
                D=result["moves"],
            )
            rows.append(row)
            print(json.dumps(row), flush=True)
    return dict(ratio=sum(r["candidate"] / r["baseline"] for r in rows) / len(rows), rows=rows)


if __name__ == "__main__":
    print(json.dumps(measure()), flush=True)
