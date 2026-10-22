"""Frozen paired comparison of dispatch ownership and reservation coordination."""

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.runner.f_research import run as portfolio
from agv.runner.joint_research import run
from agv.warehouse.mixed import generate_current

VARIANTS = ("portfolio", "assignment", "priority", "combined", "random", "aco", "pso")


def worker(case):
    size, mode, seed, variants, optimizer_seeds, out, budget = case
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
        row = dict(map=size, mode=mode, seed=seed, variant=variant, optimizer_seed=optimizer_seed)
        start, cpu = perf_counter(), process_time()
        try:
            raw = (
                portfolio(scene, method="portfolio", optimizer_seed=optimizer_seed)
                if variant == "portfolio"
                else run(
                    scene, mode=variant, candidate_budget=budget, optimizer_seed=optimizer_seed
                )
            )
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
            joint = result.get("joint_search", {})
            decisions = joint.get("decisions", [])
            anchor = (
                [a for d in decisions for a in d.get("baseline_decisions", [])]
                if joint
                else result.get("f_search", {}).get("decisions", [])
            )
            row["anchor_previews"] = sum(1 + len(d.get("candidates", [])) for d in anchor)
            row["additional_previews"] = sum(d.get("previews", 1) for d in decisions)
            row["additional_route_calls"] = (
                sum(d.get("route_calls", 0) for d in decisions) if joint else None
            )
            row["additional_expanded"] = (
                sum(d.get("expanded", 0) for d in decisions) if joint else None
            )
            row["joint_proxy_evaluations"] = (
                sum(d.get("stats", {}).get("unique_evaluations", 0) for d in decisions)
                if joint
                else None
            )
            row["commit_mismatches"] = sum(
                f["prediction_mismatch"] for f in joint.get("commit_feedback", [])
            )
            row["commit_rejections"] = sum(f["rejected"] for f in joint.get("commit_feedback", []))
            Path(out, "traces", f"{size}-{mode}-{seed}-{variant}-{optimizer_seed}.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as error:
            row.update(valid=False, error=f"{type(error).__name__}: {error}")
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=("pilot", "dev", "final", "robust"), default="dev")
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--optimizer-seeds", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--candidate-budget", type=int, default=8)
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
    seeds = {
        "pilot": [8099],
        "dev": list(range(8100, 8103)),
        "final": list(range(18100, 18106)),
        "robust": [19100, 19101],
    }[args.phase]
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    for directory in ("scenes", "traces"):
        (out / directory).mkdir()
    before = fingerprints()
    protocol = dict(
        phase=args.phase,
        maps=maps,
        modes=["static", "dynamic"],
        seeds=seeds,
        variants=variants,
        optimizer_seeds=list(map(int, args.optimizer_seeds.split(","))),
        candidate_budget=args.candidate_budget,
        proxy_budget=192,
        weights=[0.5, 0.3, 0.2],
        primary="paired F gain against previous portfolio",
        selection="development only; one candidate; no R or P90 guard",
        visibility="published jobs only",
        budget_note="same additional upper caps; priority has fewer unique permutations; count actual previews; portfolio internal proxy/route calls uninstrumented, not zero",
    )
    (out / "freeze.json").write_text(
        json.dumps(dict(protocol=protocol, source_sha256=before), indent=2), encoding="utf-8"
    )
    rows = []
    cases = [
        (m, mode, s, variants, protocol["optimizer_seeds"], str(out), args.candidate_budget)
        for m in maps
        for mode in protocol["modes"]
        for s in seeds
    ]
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
