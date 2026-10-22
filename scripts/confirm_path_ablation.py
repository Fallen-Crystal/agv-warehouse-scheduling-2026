"""Pre-outcome dynamic ablation: selected ACO dispatch with plain SIPP timing."""

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.path_research import run
from agv.warehouse.mixed import generate_current


def worker(case):
    size, seed, out, optimizer_seed = case
    scene = generate_current(
        size=size,
        seed=seed,
        vehicles=4,
        task_count=8,
        mode="dynamic",
        arrival="burst",
        horizon=None,
        shelf_layers=8,
    )
    suffix = f"-{optimizer_seed}" if optimizer_seed else ""
    Path(out, "scenes", f"{size}-dynamic-{seed}{suffix}.json").write_text(
        json.dumps(scene.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    row = dict(
        map=size, mode="dynamic", seed=seed, variant="aco__sipp", optimizer_seed=optimizer_seed
    )
    start = process_time()
    try:
        raw = run(scene, route="sipp", orders="aco", optimizer_seed=optimizer_seed)
        row["cpu_seconds"] = process_time() - start
        r = score_result(scene, raw)
        validate(scene, r)
        if not r["score_valid"]:
            raise ValueError("Incomplete ablation execution")
        info = r["path_research"]
        anchor = [d for x in info["decisions"] for d in x.get("baseline_decisions", [])]
        row.update(
            valid=True,
            F=r["weighted_score"],
            T=r["makespan"],
            R=r["mean_flow_time"],
            D=r["moves"],
            nt=r["normalized_time"],
            nr=r["normalized_response"],
            nd=r["normalized_distance"],
            p90=r["p90_flow_time"],
            anchor_previews=sum(1 + len(d.get("candidates", [])) for d in anchor),
            additional_previews=sum(d.get("previews", 1) for d in info["decisions"]),
        )
        Path(out, "traces", f"{size}-dynamic-{seed}-aco__sipp-{optimizer_seed}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as error:
        row.update(valid=False, error=f"{type(error).__name__}: {error}")
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--phase", choices=("final", "robust"), default="final")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    for name in ("scenes", "traces"):
        (a.output / name).mkdir()
    before = fingerprints()
    protocol = dict(
        source_sha256=before,
        seeds=list(range(18100, 18106)) if a.phase == "final" else [19100, 19101],
        optimizer_seeds=[0] if a.phase == "final" else [1, 2],
        maps=["medium", "large", "xlarge", "xxlarge"],
        orders="aco",
        route="sipp",
        role="component-removal ablation; same scenes and optimizer seed as primary; not a retuning run",
    )
    (a.output / "freeze.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    rows = []
    with (a.output / "rows.jsonl").open("w", encoding="utf-8") as log:
        with ProcessPoolExecutor(max_workers=2) as pool:
            for future in as_completed(
                [
                    pool.submit(worker, (m, s, str(a.output), optimizer_seed))
                    for m in protocol["maps"]
                    for s in protocol["seeds"]
                    for optimizer_seed in protocol["optimizer_seeds"]
                ]
            ):
                row = future.result()
                rows.append(row)
                log.write(json.dumps(row) + "\n")
                log.flush()
                print(
                    json.dumps(dict(runs=len(rows), valid=sum(r["valid"] for r in rows))),
                    flush=True,
                )
    if before != fingerprints():
        raise ValueError("Source changed during ablation")
    with (a.output / "runs.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        w.writeheader()
        w.writerows(rows)
    (a.output / "summary.json").write_text(
        json.dumps(
            dict(runs=len(rows), valid=sum(r["valid"] for r in rows), source_unchanged=True),
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
