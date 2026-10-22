"""Paired fixed-F development/holdout study; preserve failures and raw traces."""

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.f_research import run as run_new
from agv.runner.research import run as run_v1
from agv.warehouse.mixed import generate_current

VARIANTS = {
    "greedy": None,
    "v1": None,
    "matching": dict(method="matching"),
    "random": dict(method="random"),
    "ga_nomat": dict(matching=False),
    "ga_uncal": dict(calibrated=False),
    **{f"ga_{t}": dict(terms=t) for t in ("T", "R", "D", "TR", "TD", "RD", "TRD")},
    "hybrid": dict(method="hybrid"),
    "portfolio": dict(method="portfolio"),
}


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
    jobs = [
        (v, s)
        for v in variants
        for s in ([0] if v in ("greedy", "v1", "matching") else optimizer_seeds)
    ]
    shift = seed % len(jobs)
    jobs = jobs[shift:] + jobs[:shift]
    rows = []
    for variant, optimizer_seed in jobs:
        row = dict(map=size, mode=mode, seed=seed, variant=variant, optimizer_seed=optimizer_seed)
        start, cpu = perf_counter(), process_time()
        try:
            raw = (
                run_v1(scene, mode="greedy" if variant == "greedy" else "ga")
                if variant in ("greedy", "v1")
                else run_new(scene, optimizer_seed=optimizer_seed, **VARIANTS[variant])
            )
            row.update(cpu_seconds=process_time() - cpu, wall_seconds=perf_counter() - start)
            result = score_result(scene, raw)
            validate(scene, result)
            if not result["score_valid"]:
                raise ValueError("No valid complete score")
            row.update(
                valid=True,
                F=result["weighted_score"],
                T=result["makespan"],
                R=result["mean_flow_time"],
                D=result["moves"],
                nt=result["normalized_time"],
                nr=result["normalized_response"],
                nd=result["normalized_distance"],
            )
            flows = sorted(
                e["delivery_end"] - next(j.release for j in scene.tasks if j.id == e["task_id"])
                for e in result["events"]
            )
            row["p90"] = flows[(9 * len(flows) + 9) // 10 - 1]
            decisions = result.get("f_search", {}).get("decisions", [])
            row["proxy_evaluations"] = sum(
                d.get("stats", {}).get("unique_evaluations", 0) for d in decisions
            )
            row["candidate_rollouts"] = sum(len(d.get("candidates", [])) for d in decisions)
            trace = Path(out, "traces", f"{size}-{mode}-{seed}-{variant}-{optimizer_seed}.json")
            trace.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception as error:
            row.update(valid=False, error=f"{type(error).__name__}: {error}")
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=("pilot", "dev", "final"), default="dev")
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--optimizer-seeds", default="0")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed-start", type=int)
    args = parser.parse_args()
    variants = args.variants.split(",")
    if any(v not in VARIANTS for v in variants):
        raise ValueError("Unknown variant")
    maps = (
        ["medium"]
        if args.phase == "pilot"
        else ["medium", "large"]
        if args.phase == "dev"
        else ["medium", "large", "xlarge", "xxlarge"]
    )
    seeds = (
        [4099]
        if args.phase == "pilot"
        else list(range(4100, 4103))
        if args.phase == "dev"
        else list(range(6100, 6106))
    )
    if args.seed_start is not None:
        seeds = list(range(args.seed_start, args.seed_start + len(seeds)))
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    for name in ("scenes", "traces"):
        (out / name).mkdir()
    before = fingerprints()
    protocol = dict(
        phase=args.phase,
        maps=maps,
        modes=["static", "dynamic"],
        seeds=seeds,
        variants=variants,
        optimizer_seeds=list(map(int, args.optimizer_seeds.split(","))),
        weights=[0.5, 0.3, 0.2],
        references="official same-scene fixed reference",
        future_visibility="published only",
        primary="mean paired F vs frozen v1; not per-case best",
    )
    (out / "freeze.json").write_text(
        json.dumps(dict(protocol=protocol, source_sha256=before), indent=2), encoding="utf-8"
    )
    cases = [
        (m, mode, seed, variants, protocol["optimizer_seeds"], str(out))
        for m in maps
        for mode in protocol["modes"]
        for seed in seeds
    ]
    rows = []
    with (out / "rows.jsonl").open("w", encoding="utf-8") as log:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
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
    keys = sorted(set().union(*(r.keys() for r in rows)))
    with (out / "runs.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
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
