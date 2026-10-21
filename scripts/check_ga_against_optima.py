import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.runner.research import run
from agv.warehouse.scenarios import Scenario

rows = []
for path in sorted(Path("runs/multi-exact-reference").glob("*.json")):
    if path.name == "summary.json":
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    s = Scenario.from_dict(data["scene"])
    r = score_result(s, run(s, mode="ga"))
    optimum = data["certificate"]["relaxed_lower_F"]
    row = dict(
        case=path.stem,
        valid=r["score_valid"],
        F=r["weighted_score"],
        optimal_F=optimum,
        gap_pct=100 * (r["weighted_score"] / optimum - 1),
        reaches_optimum=abs(r["weighted_score"] - optimum) < 1e-12,
    )
    rows.append(row)
    print(json.dumps(row), flush=True)
Path("runs/ga-vs-multi-optima.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
