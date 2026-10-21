import json
from dataclasses import replace
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.runner.research import run
from agv.warehouse.mixed import generate_current

rows = []
for size, seed in (("medium", 2000), ("xxlarge", 2001)):
    s = generate_current(
        size=size,
        seed=seed,
        vehicles=10,
        task_count=12,
        mode="dynamic",
        arrival="burst",
        shelf_layers=8,
        horizon=None,
    )
    s.tasks = [replace(j, delivery=s.stations[0], release=j.release * 10) for j in s.tasks]
    s.order_stream_end = max(j.release for j in s.tasks) + 30
    s.check()
    try:
        r = score_result(s, run(s, mode="ga"))
        validate(s, r)
        if not r["score_valid"]:
            raise ValueError("Not complete/scorable")
        rows.append(
            dict(
                size=size,
                seed=seed,
                valid=True,
                F=r["weighted_score"],
                T=r["makespan"],
                D=r["moves"],
                completed=r["completed"],
            )
        )
        Path(f"runs/stress-{size}.json").write_text(
            json.dumps(dict(scene=s.to_dict(), result=r)), encoding="utf-8"
        )
    except Exception as error:
        rows.append(dict(size=size, seed=seed, valid=False, error=str(error)))
    print(json.dumps(rows[-1]), flush=True)
Path("runs/research-stress.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
