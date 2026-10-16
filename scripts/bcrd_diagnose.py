#!/usr/bin/env python3
"""Stage A: audit retained V4 traces and enumerate visible first batches only.

The small reference searches initial ordered assignments, then always follows
one fixed legal greedy policy. It is not a globally optimal schedule/oracle.
Offline V4 denominators rank diagnostic results; no online action sees them.
"""

import argparse
import csv
import hashlib
import itertools
import json
import subprocess
import time
from pathlib import Path
from statistics import mean

from agv.dispatch.greedy import greedy_action
from agv.dispatch.optimized import matching_action
from agv.evaluation.dispatch_analysis import analyze_dispatch
from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.io.scenes import pack_scene, scenario_id, unpack_scene
from agv.simulation import Environment
from agv.warehouse.layout import generate

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def legalize(observation, pairs):
    """Preserve preference order while excluding same-face batch duplicates."""
    jobs = {job["id"]: job for job in observation["pending"]}
    used, out = set(), []
    for vehicle, job in pairs:
        face = tuple(jobs[job]["shelf"])
        if face not in used:
            used.add(face)
            out.append((vehicle, job))
    return out


def rollout(scene, first):
    """All candidate differences stop after t=0; same SIPP + no joint afterward."""
    env = Environment(scene, router_kind="sipp")
    initial_feedback = env.assign(first)
    while not env.done and (scene.horizon is None or env.time < scene.horizon):
        if env.time == 0:
            feedback = initial_feedback
        else:
            observation = env.observe()
            feedback = env.assign(legalize(observation, greedy_action(observation)))
        if env.stop_if_stalled(feedback):
            break
        env.advance(observe=False)
    result = env.result()
    validate(scene, result)
    return result, initial_feedback


def summarize_result(scene, result, batch, reference, seconds):
    scored = score_result(scene, result, reference)
    return dict(
        ordered_batch=[list(pair) for pair in batch],
        feasible=result["feasible"],
        completed=result["completed"],
        total_tasks=len(scene.tasks),
        makespan=result["makespan"],
        mean_flow_time=result["mean_flow_time"],
        p90_flow_time=result["p90_flow_time"],
        moves=result["moves"],
        weighted_score=scored["weighted_score"],
        runtime_seconds=seconds,
    )


def small_reference(output, delivery_pattern):
    scene = generate(seed=10, task_count=5, vehicles=2, delivery_pattern=delivery_pattern)
    observation = Environment(scene, router_kind="sipp").observe()
    assert len(observation["pending"]) == len(scene.tasks), "Small search must see every order"
    reference = reference_context(scene)  # Offline scoring only.
    jobs = {job["id"]: job for job in observation["pending"] if job["dispatchable"]}
    safe = legalize(observation, greedy_action(observation))
    matching = legalize(observation, matching_action(observation))
    trials, traces = [], {}
    actions = {tuple(safe), tuple(matching)}
    for ids in itertools.permutations(jobs, 2):
        if jobs[ids[0]]["shelf"] == jobs[ids[1]]["shelf"]:
            continue
        for vehicles in ((0, 1), (1, 0)):
            actions.add(tuple(zip(vehicles, ids)))
    for action in sorted(actions):
        started = time.perf_counter()
        result, feedback = rollout(scene, action)
        seconds = time.perf_counter() - started
        item = summarize_result(scene, result, action, reference, seconds)
        item["initial_feedback"] = feedback
        trials.append(item)
        traces[action] = result
    successful = [row for row in trials if row["feasible"]]
    best = min(successful, key=lambda row: (row["weighted_score"], row["ordered_batch"]))
    by_action = {tuple(map(tuple, row["ordered_batch"])): row for row in trials}
    base, matched = by_action[tuple(safe)], by_action[tuple(matching)]
    # Pre-selected reproducible order counterexample from development seed 10.
    # It need not be the greedy pairing; it isolates sequential reservation semantics.
    order_a = ((1, 0), (0, 3))
    order_b = order_a[::-1]
    relevant = {"greedy": tuple(safe), "matching": tuple(matching)}
    relevant["best_initial_batch"] = tuple(map(tuple, best["ordered_batch"]))
    if delivery_pattern == "shared":
        relevant.update(order_a=order_a, order_b=order_b)
    case_root = output / "small_cases" / delivery_pattern
    write_json(case_root / "input.json", pack_scene(scene))
    for name, action in relevant.items():
        write_json(
            case_root / f"{name}.json",
            pack_scene(
                scene,
                {"router": "sipp", "joint": False, "initial_batch": action},
                score_result(scene, traces[action], reference),
            ),
        )
    summary = dict(
        scenario_sha256=scenario_id(scene),
        configuration=dict(seed=10, task_count=5, vehicles=2, delivery_pattern=delivery_pattern),
        backend="sipp",
        joint=False,
        scope="all legal maximum-cardinality initial ordered batches, then fixed legal greedy",
        globally_optimal=False,
        trials=len(trials),
        successful_trials=len(successful),
        greedy=base,
        matching=matched,
        best_initial_batch=best,
        improvement_vs_greedy_pct=100
        * (base["weighted_score"] - best["weighted_score"])
        / base["weighted_score"],
    )
    if delivery_pattern == "shared":
        summary["order_counterexample"] = [by_action[order_a], by_action[order_b]]
    write_json(case_root / "all_trials.json", trials)
    write_json(case_root / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/bcrd/diagnosis")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    baseline_rows = list(csv.DictReader((ROOT / "results/v4/runs.csv").open(encoding="utf-8-sig")))
    row_index = {(row["scenario"], row["solver"], int(row["seed"])): row for row in baseline_rows}
    summaries, task_rows, fleet_rows, inputs = [], [], [], {}
    for path in sorted((ROOT / "results/v4/traces").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scene = unpack_scene(data)
        result = data["result"]
        validate(scene, result)
        ledger = analyze_dispatch(scene, result)
        name, solver = path.stem.rsplit("-", 1)
        original = row_index[name, solver, 0]
        key = dict(scenario=name, solver=solver, seed=0)
        write_json(output / "ledgers" / path.name, ledger)
        summaries.append(
            dict(
                **key,
                successful=ledger["execution_successful"],
                total_tasks=ledger["total_tasks"],
                completed_tasks=ledger["completed_tasks"],
                makespan=result["makespan"],
                moves=result["moves"],
                p90_flow_time=ledger["p90_flow_time"],
                runtime_seconds=original["runtime_seconds"],
                **ledger["means"],
            )
        )
        task_rows.extend(dict(**key, **row) for row in ledger["tasks"])
        fleet_rows.extend(dict(**key, **row) for row in ledger["fleet"])
        inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_csv(output / "baseline_metrics.csv", summaries)
    write_csv(output / "task_ledger.csv", task_rows)
    write_csv(output / "fleet_ledger.csv", fleet_rows)
    aggregate_rows = []
    for name, solver in sorted({(r["scenario"], r["solver"]) for r in baseline_rows}):
        own = [r for r in baseline_rows if (r["scenario"], r["solver"]) == (name, solver)]
        aggregate_rows.append(
            dict(
                scenario=name,
                solver=solver,
                samples=len(own),
                failures=sum(r["feasible"] != "True" for r in own),
                **{
                    field + "_mean": mean(float(r[field]) for r in own)
                    for field in ("mean_flow_time", "p90_flow_time", "runtime_seconds")
                },
            )
        )
    write_csv(output / "historical_54_summary.csv", aggregate_rows)
    cases = {pattern: small_reference(output, pattern) for pattern in ("distributed", "shared")}
    write_json(output / "summary.json", dict(traces=summaries, small_cases=cases))
    write_json(
        output / "manifest.json",
        dict(
            stage="A",
            baseline_commit="8551943e1b248c05ba5e12cab0570dd6d2f59975",
            current_commit=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            retained_trace_hashes=inputs,
            analysis_source_sha256={
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (
                    ROOT / "scripts/bcrd_diagnose.py",
                    ROOT / "src/agv/evaluation/dispatch_analysis.py",
                )
            },
            historical_traces_validated=6,
            task_ledgers_reconciled=len(task_rows),
            historical_runs_summarized=54,
            development_seeds=[10],
            holdout_results_accessed=False,
            notes="No old trace or score overwritten. Small reference reads all currently released tasks, never a future order. Stationary path steps are observable waits, not causal traffic/gate attribution. No online denominator access.",
        ),
    )
    print(
        json.dumps(
            {key: value["improvement_vs_greedy_pct"] for key, value in cases.items()}, indent=2
        )
    )


if __name__ == "__main__":
    main()
