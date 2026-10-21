"""Find exact multi-car witnesses by attainment of all proven lower bounds."""

import json
from pathlib import Path

from agv.evaluation.bounds import lower_bounds
from agv.evaluation.validation import validate
from agv.registry import run_raw
from agv.warehouse.mixed import generate_current

rows, found = [], []
out = Path("runs/multi-optimal-certificates")
out.mkdir(exist_ok=True)
for size in ("medium", "large", "xlarge", "xxlarge"):
    for seed in range(60, 70):
        s = generate_current(
            size=size,
            seed=seed,
            vehicles=2,
            task_count=2,
            mode="static",
            shelf_layers=8,
            horizon=None,
        )
        b = lower_bounds(s)
        r = run_raw("sipp_stream_dispatch", s)
        validate(s, r)
        tight = (
            r["makespan"] == b["T"]
            and abs(r["mean_flow_time"] - b["R"]) < 1e-12
            and r["moves"] == b["D"]
        )
        row = dict(
            size=size,
            seed=seed,
            T=r["makespan"],
            R=r["mean_flow_time"],
            D=r["moves"],
            lower=b,
            tight=tight,
        )
        rows.append(row)
        if tight:
            found.append(row)
            (out / f"{size}-{seed}.json").write_text(
                json.dumps(dict(scene=s.to_dict(), result=r, certificate=row)), encoding="utf-8"
            )
        print(json.dumps(dict(size=size, seed=seed, tight=tight)), flush=True)
(out / "summary.json").write_text(
    json.dumps(dict(rows=rows, exact_certificates=found), indent=2), encoding="utf-8"
)
print("EXACT", len(found), "TOTAL", len(rows), flush=True)
