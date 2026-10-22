"""Paired actual-path hybrid screening and frozen regime-specific confirmation."""

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.path_research import ROUTES, run
from agv.warehouse.mixed import generate_current


def worker(case):
    size, mode, seed, variants, optimizer_seeds, out = case
    scene = generate_current(
        size=size,
        seed=seed,
        vehicles=4,
        task_count=12 if mode == "static" else 8,
        mode=mode,
        arrival="burst",
        horizon=None,
        shelf_layers=8,
    )
    Path(out, "scenes", f"{size}-{mode}-{seed}.json").write_text(
        json.dumps(scene.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    jobs = [(v, s) for v in variants for s in optimizer_seeds]
    shift = seed % len(jobs)
    jobs = jobs[shift:] + jobs[:shift]
    rows = []
    for variant, optimizer_seed in jobs:
        orders, route = variant.split("__")
        row = dict(map=size, mode=mode, seed=seed, variant=variant, optimizer_seed=optimizer_seed)
        start, cpu, raw = perf_counter(), process_time(), None
        try:
            raw = run(scene, route=route, orders=orders, optimizer_seed=optimizer_seed)
            row.update(cpu_seconds=process_time() - cpu, wall_seconds=perf_counter() - start)
            result = score_result(scene, raw)
            validate(scene, result)
            if not result["score_valid"]:
                raise ValueError(
                    f"Incomplete execution: {result.get('reason')}; {result.get('diagnostics')}"
                )
            row.update(
                valid=True,
                F=result["weighted_score"],
                T=result["makespan"],
                R=result["mean_flow_time"],
                D=result["moves"],
                nt=result["normalized_time"],
                nr=result["normalized_response"],
                nd=result["normalized_distance"],
                p90=result["p90_flow_time"],
            )
            info = result["path_research"]
            decisions = info["decisions"]
            anchor = (
                decisions
                if orders == "portfolio"
                else [d for x in decisions for d in x.get("baseline_decisions", [])]
            )
            row["anchor_previews"] = sum(1 + len(d.get("candidates", [])) for d in anchor)
            row["additional_previews"] = (
                0 if orders == "portfolio" else sum(d.get("previews", 1) for d in decisions)
            )
            row["commit_mismatches"] = sum(
                r["prediction_mismatch"] for r in info["commit_feedback"]
            )
            row["commit_rejections"] = sum(r["rejected"] for r in info["commit_feedback"])
            row.update({"path_" + k: v for k, v in info["diagnostics"].items()})
            row.update({"actual_router_" + k: v for k, v in result["routing_stats"].items()})
            Path(out, "traces", f"{size}-{mode}-{seed}-{variant}-{optimizer_seed}.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as error:
            row.update(valid=False, error=f"{type(error).__name__}: {error}")
            if raw is not None:
                Path(
                    out, "failures", f"{size}-{mode}-{seed}-{variant}-{optimizer_seed}.json"
                ).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--phase", choices=("pilot", "dev", "final", "robust"), default="dev")
    p.add_argument("--selection")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--optimizer-seeds", default="0")
    a = p.parse_args()
    maps = (
        ["medium"]
        if a.phase == "pilot"
        else ["medium", "large"]
        if a.phase == "dev"
        else ["medium", "large", "xlarge", "xxlarge"]
    )
    seeds = {
        "pilot": [8098],
        "dev": list(range(8100, 8103)),
        "final": list(range(18100, 18106)),
        "robust": [19100, 19101],
    }[a.phase]
    if a.phase in ("pilot", "dev"):
        variants = {
            mode: [
                f"{o}__{r}"
                for o in (
                    ["portfolio", "assignment"]
                    if mode == "static"
                    else ["portfolio", "assignment", "aco"]
                )
                for r in ROUTES
            ]
            for mode in ("static", "dynamic")
        }
    else:
        if not a.selection:
            p.error("A pre-frozen development selection is required")
        selection = json.loads(Path(a.selection).read_text(encoding="utf-8"))
        variants = {
            mode: list(dict.fromkeys(["portfolio__sipp", "assignment__sipp", selection[mode]]))
            for mode in ("static", "dynamic")
        }
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    for name in ("scenes", "traces", "failures"):
        (out / name).mkdir()
    before = fingerprints()
    protocol = dict(
        phase=a.phase,
        maps=maps,
        seeds=seeds,
        variants_by_mode=variants,
        optimizer_seeds=list(map(int, a.optimizer_seeds.split(","))),
        weights=[0.5, 0.3, 0.2],
        routing_budget="four timed alternatives and twelve spatial proposals per leg; actual counts retained",
        primary="paired F against portfolio+SIPP; selection by development only",
        future_visibility="geometry and committed reservations; published tasks only",
        regime="known static or dynamic experimental setting; no future release timestamps supplied",
    )
    (out / "freeze.json").write_text(
        json.dumps(dict(protocol=protocol, source_sha256=before), indent=2), encoding="utf-8"
    )
    cases = [
        (m, mode, s, variants[mode], protocol["optimizer_seeds"], str(out))
        for m in maps
        for mode in ("static", "dynamic")
        for s in seeds
    ]
    rows = []
    with (out / "rows.jsonl").open("w", encoding="utf-8") as log:
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            for future in as_completed([pool.submit(worker, c) for c in cases]):
                batch = future.result()
                for row in batch:
                    log.write(json.dumps(row) + "\n")
                log.flush()
                rows.extend(batch)
                print(
                    json.dumps(
                        dict(
                            done=len(rows),
                            valid=sum(r["valid"] for r in rows),
                            case=[batch[0][k] for k in ("map", "mode", "seed")],
                        )
                    ),
                    flush=True,
                )
    if before != fingerprints():
        raise RuntimeError("Source changed during frozen evaluation")
    with (out / "runs.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(
        protocol=protocol,
        runs=len(rows),
        valid=sum(r["valid"] for r in rows),
        source_unchanged=True,
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
