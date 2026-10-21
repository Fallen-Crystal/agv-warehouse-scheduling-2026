"""Frozen paired evaluation of textbook permutation GA and priority search.

Run with python -m agv.experiments.search_benchmark --output runs/search-holdout.
The sole source of algorithm input remains an observation. Exact certificates
are offline diagnostics, never features or candidate normalization factors.
"""

import argparse
import hashlib
import json
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from time import perf_counter, process_time

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.planning.order_search import exact_single
from agv.registry import run_raw
from agv.runner.research import run
from agv.warehouse.mixed import generate_current

POLICIES = ("greedy", "ga")
PROTOCOL = dict(
    development_seeds=[60, 61],
    holdout_seeds=list(range(3000, 3006)),
    maps=["medium", "large", "xlarge", "xxlarge"],
    strata={
        "single_static": dict(vehicles=1, task_count=8, mode="static"),
        "multi_static": dict(vehicles=4, task_count=12, mode="static"),
        "multi_dynamic": dict(vehicles=4, task_count=8, mode="dynamic", arrival="burst"),
    },
    primary="ga_vs_greedy",
    secondary="priority ablations; existing BCRD/ETA comparators",
    adoption="positive paired mean F gain with positive bootstrap lower endpoint; no execution invalidity",
    caveat="Fixed synthetic layout family, six new seeds; seed-cluster bootstrap, not unseen-map validation",
)


def fingerprints():
    root = Path(__file__).resolve().parents[3]
    return {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "src/agv").rglob("*"))
        if p.suffix in (".py", ".json", ".js", ".html", ".css")
    }


def worker(case):
    size, stratum, seed, out = case
    options = dict(PROTOCOL["strata"][stratum])
    scene = generate_current(size=size, seed=seed, horizon=None, shelf_layers=8, **options)
    scene_raw = json.dumps(scene.to_dict(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(scene_raw.encode()).hexdigest()
    policies = list(POLICIES)
    if stratum == "multi_static" and seed in (3000, 3001):
        policies += ["priority", "ga_priority"]
    if size in ("medium", "large") and stratum != "single_static":
        policies += ["bcrd_tail", "eta_delay"]
    shift = seed % len(policies)
    policies = policies[shift:] + policies[:shift]
    rows = []
    certificate = exact_single(scene) if stratum == "single_static" else None
    for policy in policies:
        start, cpu = perf_counter(), process_time()
        row = dict(map=size, stratum=stratum, seed=seed, policy=policy, scene_sha256=digest)
        try:
            if policy in ("bcrd_tail", "eta_delay"):
                raw = run_raw(
                    "sipp_stream_bcrd_tail"
                    if policy == "bcrd_tail"
                    else "sipp_position_delay_dispatch",
                    scene,
                )
            else:
                raw = run(
                    scene,
                    mode="ga" if policy.startswith("ga") else "greedy",
                    coordinate="priority" in policy,
                )
            solve_cpu, solve_wall = process_time() - cpu, perf_counter() - start
            result = score_result(scene, raw)
            validate(scene, result)
            if not result["score_valid"]:
                raise ValueError("Execution is not valid for scoring")
            row.update(
                valid=True,
                F=result["weighted_score"],
                T=result["makespan"],
                R=result["mean_flow_time"],
                D=result["moves"],
                cpu_seconds=solve_cpu,
                wall_seconds=solve_wall,
            )
            # Metrics are produced by the existing evaluator; locate schema
            # explicitly, never invent a substitute score on failure.
            flows = sorted(
                e["delivery_end"] - next(j.release for j in scene.tasks if j.id == e["task_id"])
                for e in result["events"]
            )
            row["p90"] = flows[(9 * len(flows) + 9) // 10 - 1]
            if certificate:
                row.update(
                    optimal_F=certificate["optimal_score"],
                    optimality_gap_pct=100 * (row["F"] / certificate["optimal_score"] - 1),
                )
            trace = Path(out) / "traces" / f"{size}-{stratum}-{seed}-{policy}.json"
            trace.write_text(
                json.dumps(dict(scene=scene.to_dict(), result=result), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as error:
            row.update(
                valid=False,
                error=f"{type(error).__name__}: {error}",
                cpu_seconds=process_time() - cpu,
                wall_seconds=perf_counter() - start,
            )
        rows.append(row)
    if certificate:
        Path(out, "certificates", f"{size}-{seed}.json").write_text(
            json.dumps(certificate, indent=2), encoding="utf-8"
        )
    return rows


def summarize(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["map"], r["stratum"], r["seed"]), {})[r["policy"]] = r
    output = {}
    comparisons = [
        (p, "greedy") for p in ("ga", "priority", "ga_priority", "bcrd_tail", "eta_delay")
    ]
    comparisons += [("ga_priority", "ga"), ("ga", "bcrd_tail"), ("ga", "eta_delay")]
    for candidate, baseline in comparisons:
        for stratum in ("all", *PROTOCOL["strata"]):
            pairs = [
                (g[baseline], g[candidate])
                for k, g in groups.items()
                if baseline in g and candidate in g and (stratum == "all" or k[1] == stratum)
            ]
            valid = [(b, c) for b, c in pairs if b["valid"] and c["valid"]]
            if not valid:
                continue
            gains = [100 * (b["F"] - c["F"]) / b["F"] for b, c in valid]
            rng = random.Random(71021)
            clusters = {}
            for b, c in valid:
                clusters.setdefault(b["seed"], []).append(100 * (b["F"] - c["F"]) / b["F"])
            cluster_means = [mean(v) for v in clusters.values()]
            means = sorted(
                mean(rng.choices(cluster_means, k=len(cluster_means))) for _ in range(5000)
            )
            output[f"{candidate}/{baseline}/{stratum}"] = dict(
                pairs=len(pairs),
                valid_pairs=len(valid),
                mean_gain_pct=mean(gains),
                ci95=[means[124], means[4874]],
                bootstrap_seed_clusters=len(clusters),
                wins=sum(x > 1e-9 for x in gains),
                losses=sum(x < -1e-9 for x in gains),
                ties=sum(abs(x) <= 1e-9 for x in gains),
                p90_worse=sum(c["p90"] > b["p90"] for b, c in valid),
                mean_cpu_ratio=mean(c["cpu_seconds"] / b["cpu_seconds"] for b, c in valid),
                mean_D_delta=mean(c["D"] - b["D"] for b, c in valid),
            )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "traces").mkdir()
    (out / "certificates").mkdir()
    before = fingerprints()
    (out / "freeze.json").write_text(
        json.dumps(dict(protocol=PROTOCOL, source_sha256=before), indent=2), encoding="utf-8"
    )
    cases = [
        (size, stratum, seed, str(out))
        for size in PROTOCOL["maps"]
        for stratum in PROTOCOL["strata"]
        for seed in PROTOCOL["holdout_seeds"]
    ]
    rows = []
    with (out / "rows.jsonl").open("w", encoding="utf-8") as log:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(worker, c) for c in cases]):
                result = future.result()
                for row in result:
                    log.write(json.dumps(row) + "\n")
                log.flush()
                rows.extend(result)
                print(
                    json.dumps(
                        dict(
                            done=len(rows),
                            case=[result[0][k] for k in ("map", "stratum", "seed")],
                            valid=sum(r["valid"] for r in result),
                        )
                    ),
                    flush=True,
                )
    if before != fingerprints():
        raise RuntimeError("Source changed during frozen evaluation")
    summary = dict(
        protocol=PROTOCOL,
        runs=len(rows),
        valid=sum(r["valid"] for r in rows),
        source_unchanged=True,
        comparisons=summarize(rows),
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
