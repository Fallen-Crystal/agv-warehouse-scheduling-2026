"""Physical trace equivalence after diagnostics-only and allocation-cost cleanup."""

import argparse
import hashlib
import json
from pathlib import Path

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.path_research import run
from agv.warehouse.scenarios import Scenario


def signature(result):
    fields = (
        "paths",
        "events",
        "assignments",
        "moves",
        "makespan",
        "time",
        "mean_flow_time",
        "empty_moves",
        "loaded_moves",
        "traffic_wait_steps",
    )
    return hashlib.sha256(
        json.dumps({k: result[k] for k in fields}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("development", type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    before, rows = fingerprints(), []
    for size in ("medium", "large"):
        for mode in ("static", "dynamic"):
            order = "assignment" if mode == "static" else "aco"
            routes = (
                ("sipp", "aco_sipp", "pso_astar")
                if mode == "static"
                else ("astar", "aco_astar", "pso_sipp")
            )
            stem = f"{size}-{mode}-8100"
            scene = Scenario.from_dict(
                json.loads(
                    (a.development / "scenes" / (stem + ".json")).read_text(encoding="utf-8")
                )
            )
            for route in routes:
                name = f"{stem}-{order}__{route}-0.json"
                old = json.loads((a.development / "traces" / name).read_text(encoding="utf-8"))
                new = score_result(scene, run(scene, route=route, orders=order))
                validate(scene, new)
                row = dict(
                    case=name,
                    old_physical_sha256=signature(old),
                    new_physical_sha256=signature(new),
                    valid=new["score_valid"],
                )
                row["equal"] = row["old_physical_sha256"] == row["new_physical_sha256"]
                rows.append(row)
                (a.output / name).write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
                print(json.dumps(row), flush=True)
                if not row["valid"] or not row["equal"]:
                    raise ValueError("Interface cleanup changed a physical trace")
    if before != fingerprints():
        raise RuntimeError("Source changed during replay")
    (a.output / "summary.json").write_text(
        json.dumps(
            dict(
                runs=len(rows),
                all_equal=all(r["equal"] for r in rows),
                source_sha256=before,
                rows=rows,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
