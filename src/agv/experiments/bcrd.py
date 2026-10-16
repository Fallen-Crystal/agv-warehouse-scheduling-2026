"""Frozen-protocol, paired dispatch experiments on a common SIPP/no-joint backend.

Only raw algorithm execution is timed. Offline reference generation, independent
validation and V4 scoring occur outside the timer. Failed runs remain in the
matrix and never receive comparable full-task scores. A source change during a
run invalidates finalization rather than silently mixing implementations.
"""

import csv
import hashlib
import json
import math
import platform
import random
import re
import statistics
import subprocess
import time
from collections import Counter
from pathlib import Path

from agv.dispatch.bcrd import run as run_dispatch
from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.experiments.benchmark import source_hashes
from agv.experiments.v4 import CONFIGS
from agv.io.scenes import pack_scene, scenario_id
from agv.io.storage import write_json
from agv.warehouse.layout import generate

PROTOCOL_SCHEMA = "agv-bcrd-protocol-v1"
DEFAULT_SOLVERS = {
    "G0": {"policy": "greedy"},
    "G1": {"policy": "matching"},
    "G2": {"policy": "bcrd", "max_batches": 4, "depth": None, "mode": "full"},
}
ABLATION_SOLVERS = {
    **DEFAULT_SOLVERS,
    "G_order": {"policy": "bcrd", "max_batches": 4, "depth": None, "mode": "order"},
    "G_depth1": {"policy": "bcrd", "max_batches": 4, "depth": 1, "mode": "full"},
    "G_depth2": {"policy": "bcrd", "max_batches": 4, "depth": 2, "mode": "full"},
}
ROOT = Path(__file__).resolve().parents[3]
SPLIT_RANGES = {"development": (10, 19), "holdout": (30, 59), "generalization": (60, 79)}
PAIR_METRICS = ("weighted_score", "makespan", "mean_flow_time", "p90_flow_time", "moves")


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def protocol_id(protocol):
    """Semantic hash is independent of JSON whitespace and object-key order."""
    return hashlib.sha256(_canonical(protocol).encode("utf-8")).hexdigest()


def validate_protocol(protocol, *, require_frozen=False):
    if not isinstance(protocol, dict) or protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("Unknown BCRD protocol schema")
    split = protocol.get("split")
    if split not in SPLIT_RANGES:
        raise ValueError("Unknown experiment split")
    if require_frozen and (protocol.get("frozen") is not True or split == "development"):
        raise ValueError("Formal evaluation requires a pre-frozen holdout/generalization protocol")
    seeds = protocol.get("seeds")
    lower, upper = SPLIT_RANGES[split]
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(type(seed) is not int or not lower <= seed <= upper for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError(f"{split} seeds must be unique integers in {lower}..{upper}")
    for field in ("configs", "solvers"):
        values = protocol.get(field)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{field} must be a nonempty named mapping")
        for name, value in values.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not isinstance(value, dict):
                raise ValueError(f"Invalid {field} entry")
    if any("seed" in value for value in protocol["configs"].values()):
        raise ValueError("Scenario seeds belong only in protocol.seeds")
    baseline = protocol.get("baseline", "G0")
    if baseline not in protocol["solvers"] or protocol["solvers"][baseline] != {"policy": "greedy"}:
        raise ValueError("The paired baseline must be the unchanged greedy+SIPP policy")
    allowed = {
        "policy",
        "max_batches",
        "depth",
        "mode",
        "budget",
        "min_queue_ratio",
        "event_driven",
    }
    for params in protocol["solvers"].values():
        if set(params) - allowed or params.get("policy") not in ("greedy", "matching", "bcrd"):
            raise ValueError("All solvers must use the BCRD runner's SIPP/no-joint backend")
        if params["policy"] != "bcrd" and set(params) != {"policy"}:
            raise ValueError("Greedy/matching controls cannot contain unused BCRD parameters")
        ratio = params.get("min_queue_ratio", 0)
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or ratio < 0:
            raise ValueError("min_queue_ratio must be a nonnegative finite number")
    for params in protocol["solvers"].values():
        if "event_driven" in params and type(params["event_driven"]) is not bool:
            raise ValueError("event_driven must be a boolean")
    bootstrap = protocol.get("bootstrap", {"resamples": 4000, "seed": 20261016})
    if (
        not isinstance(bootstrap, dict)
        or type(bootstrap.get("resamples")) is not int
        or not 100 <= bootstrap["resamples"] <= 100000
        or type(bootstrap.get("seed")) is not int
    ):
        raise ValueError("Invalid bootstrap protocol")
    _canonical(protocol)  # Reject non-JSON/nonfinite protocol values before running.
    return protocol


def _bootstrap(values, resamples, seed):
    if not values:
        return None
    rng = random.Random(seed)
    samples = sorted(
        sum(values[rng.randrange(len(values))] for _ in values) / len(values)
        for _ in range(resamples)
    )
    return [
        samples[math.floor(0.025 * (resamples - 1))],
        samples[math.ceil(0.975 * (resamples - 1))],
    ]


def summarize(rows, protocol):
    """Paired per-instance effects; failures and missing pairs are explicit.

    Positive percent effects mean lower costs than same-backend G0. Overall
    instance means and scenario-equal means are both returned. The bootstrap
    resamples fixed-template paired instances; it is not a new-map guarantee.
    """
    baseline = protocol.get("baseline", "G0")
    config_names = list(protocol["configs"])
    solvers = list(protocol["solvers"])
    boot = protocol.get("bootstrap", {"resamples": 4000, "seed": 20261016})
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate experiment rows")
    groups = []
    for name in config_names + ["__all__"]:
        for solver in solvers:
            own = [
                r
                for r in rows
                if r["solver"] == solver and (name == "__all__" or r["scenario"] == name)
            ]
            pairs = []
            for row in own:
                other = index.get((row["scenario"], row["seed"], baseline))
                if other is None or other["scenario_sha256"] != row["scenario_sha256"]:
                    raise ValueError("Missing or mismatched paired input")
                if row["comparison_valid"] and other["comparison_valid"]:
                    pairs.append((other, row))
            effects = [
                100 * (a["weighted_score"] - b["weighted_score"]) / a["weighted_score"]
                for a, b in pairs
                if a["weighted_score"] > 0
            ]
            deltas = [b["weighted_score"] - a["weighted_score"] for a, b in pairs]
            group = dict(
                scenario=name,
                solver=solver,
                runs=len(own),
                successes=sum(r["comparison_valid"] for r in own),
                execution_failures=sum(not r["execution_valid"] or not r["feasible"] for r in own),
                incomparable_scores=sum(not r["comparison_valid"] for r in own),
                paired_successes=len(pairs),
                excluded_pairs=len(own) - len(pairs),
                score_wins=sum(delta < -1e-12 for delta in deltas),
                score_losses=sum(delta > 1e-12 for delta in deltas),
                score_ties=sum(abs(delta) <= 1e-12 for delta in deltas),
                paired_F_difference_mean=statistics.mean(deltas) if deltas else None,
                paired_F_improvement_pct_mean=statistics.mean(effects) if effects else None,
                paired_F_improvement_pct_95ci=_bootstrap(effects, boot["resamples"], boot["seed"]),
                paired_F_improvement_pct_values=effects,
                p90_degradations=sum(b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs),
                max_response_degradations=sum(
                    b["max_flow_time"] > a["max_flow_time"] for a, b in pairs
                ),
                cpu_ratio_mean=statistics.mean(
                    b["cpu_seconds"] / a["cpu_seconds"] for a, b in pairs if a["cpu_seconds"] > 0
                )
                if any(a["cpu_seconds"] > 0 for a, _ in pairs)
                else None,
                wall_ratio_mean=statistics.mean(
                    b["wall_seconds"] / a["wall_seconds"] for a, b in pairs if a["wall_seconds"] > 0
                )
                if any(a["wall_seconds"] > 0 for a, _ in pairs)
                else None,
            )
            for field in (
                "cpu_seconds",
                "wall_seconds",
                "completion_rate",
                "route_calls",
                "expanded",
                "shadow_calls",
                "shadow_route_calls",
                "shadow_expanded",
                "changed",
                "fallbacks",
            ):
                group[field + "_mean_all_runs"] = (
                    statistics.mean(r[field] for r in own) if own else None
                )
            for field in PAIR_METRICS:
                values = [b[field] for _, b in pairs]
                group[field + "_mean_paired"] = statistics.mean(values) if values else None
            groups.append(group)
    equal = []
    for solver in solvers:
        own = [g for g in groups if g["solver"] == solver and g["scenario"] != "__all__"]
        valid = [g for g in own if g["paired_F_improvement_pct_mean"] is not None]
        equal.append(
            dict(
                solver=solver,
                included_scenarios=len(valid),
                total_scenarios=len(own),
                scenario_equal_F_improvement_pct_mean=statistics.mean(
                    g["paired_F_improvement_pct_mean"] for g in valid
                )
                if valid
                else None,
            )
        )
    return dict(
        baseline=baseline,
        score_direction="lower F is better; positive paired percent improvement is better",
        pairing="same scenario SHA and seed; same SIPP backend without joint",
        overall_aggregation="__all__ is equal weight per valid paired instance; scenario_equal is equal weight per represented scenario, with exclusions disclosed",
        uncertainty="percentile bootstrap of paired instance improvements, fixed templates; no correction for algorithm selection or map generalization",
        bootstrap=boot,
        groups=groups,
        scenario_equal=equal,
    )


def _decision_summary(result):
    logs = result.get("dispatch_decisions", [])
    candidates = [candidate for row in logs for candidate in row.get("candidates", [])]
    times = sorted(row.get("cpu_seconds", 0) for row in logs)
    return dict(
        dispatch_stats=result.get("dispatch_stats", {}),
        decision_reasons=dict(Counter(row.get("reason", "unspecified") for row in logs)),
        candidate_rejection_reasons=dict(
            Counter(
                (row.get("preview_reason") or "partial_forecast")
                for row in candidates
                if not row.get("valid")
            )
        ),
        candidates_generated=sum(
            row.get("candidates_generated", len(row.get("candidates", []))) for row in logs
        ),
        candidates_evaluated=len(candidates),
        candidates_valid=sum(bool(row.get("valid")) for row in candidates),
        candidates_rejected=sum(not row.get("valid") for row in candidates),
        visible_pending_max=max((row.get("visible_pending", 0) for row in logs), default=0),
        visible_pending_evaluations=sum(row.get("visible_pending", 0) for row in logs),
        observed_task_count=result.get("observed_task_count"),
        decision_cpu_max=max(times) if times else 0,
        decision_cpu_p90=times[math.ceil(0.9 * len(times)) - 1] if times else 0,
        planning_failure_by_leg=result.get("diagnostics", {}).get("planning_failure_by_leg", {}),
        planning_failures=result.get("diagnostics", {}).get("planning_failures", []),
    )


def _row(name, seed, solver, scene, result, audit_error, elapsed_cpu, elapsed_wall):
    stats = result.get("dispatch_stats", {})
    routing = result.get("routing_stats", {})
    candidates = [
        candidate
        for decision in result.get("dispatch_decisions", [])
        for candidate in decision.get("candidates", [])
    ]
    complete = result.get("completed", 0)
    feasible = bool(result.get("feasible", False) and complete == len(scene.tasks))
    comparable = bool(audit_error is None and feasible and result.get("score_valid", False))
    row = dict(
        scenario=name,
        seed=seed,
        solver=solver,
        scenario_sha256=scenario_id(scene),
        backend="sipp",
        joint=False,
        execution_valid=audit_error is None,
        feasible=feasible,
        comparison_valid=comparable,
        completed=complete,
        total_tasks=len(scene.tasks),
        observed_task_count=result.get("observed_task_count"),
        completion_rate=complete / len(scene.tasks) if scene.tasks else 1,
        cpu_seconds=elapsed_cpu,
        wall_seconds=elapsed_wall,
        weighted_score=result.get("weighted_score") if comparable else None,
        score_valid=bool(result.get("score_valid", False) and comparable),
        reason=audit_error or result.get("reason"),
        route_calls=routing.get("calls", 0),
        expanded=routing.get("expanded", 0),
        shadow_calls=stats.get("shadow_calls", 0),
        shadow_route_calls=stats.get("shadow_route_calls", 0),
        shadow_expanded=stats.get("shadow_expanded", 0),
        changed=stats.get("changed", 0),
        fallbacks=stats.get("fallbacks", 0),
        decisions=stats.get("decisions", 0),
        searched=stats.get("searched", 0),
        candidates_evaluated=len(candidates),
        candidates_valid=sum(bool(candidate.get("valid")) for candidate in candidates),
        candidates_rejected=sum(not candidate.get("valid") for candidate in candidates),
        decision_cpu_seconds=stats.get("decision_cpu_seconds", 0),
        planning_failures=result.get("diagnostics", {}).get("planning_failure_count", 0),
    )
    for key in ("makespan", "mean_flow_time", "p90_flow_time", "max_flow_time", "moves", "time"):
        row[key] = result.get(key) if comparable else None
    return row


def _run(output, protocol, *, protocol_bytes=None):
    validate_protocol(protocol)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    raw = protocol_bytes or (
        json.dumps(protocol, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    (root / "protocol.json").write_bytes(raw)
    sources = source_hashes()
    manifest = dict(
        schema="agv-bcrd-results-v1",
        status="running",
        split=protocol["split"],
        protocol_sha256=protocol_id(protocol),
        protocol_file_sha256=hashlib.sha256(raw).hexdigest(),
        source_hashes=sources,
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        python=platform.python_version(),
        platform=platform.platform(),
        expected_runs=len(protocol["configs"]) * len(protocol["seeds"]) * len(protocol["solvers"]),
        notes="One timing per run; offline reference warmup and independent validation/scoring excluded. All failures retained. Solver order rotates by instance. Retained representative traces are not a performance sample.",
    )
    write_json(root / "manifest.json", manifest)
    rows, trace_count = [], 0
    try:
        with (
            (root / "runs.csv").open("x", encoding="utf-8", newline="") as csv_file,
            (root / "diagnostics.jsonl").open("x", encoding="utf-8", newline="\n") as diagnostics,
        ):
            writer = None
            for name, config in protocol["configs"].items():
                for position, seed in enumerate(protocol["seeds"]):
                    scene = generate(**config, seed=seed)
                    digest = scenario_id(scene)
                    reference = reference_context(scene)
                    names = list(protocol["solvers"])
                    offset = position % len(names)
                    for solver in names[offset:] + names[:offset]:
                        result, error = {}, None
                        cpu_started, wall_started = time.process_time(), time.perf_counter()
                        try:
                            result = run_dispatch(scene, **protocol["solvers"][solver])
                        except Exception as caught:
                            error = f"algorithm_error:{type(caught).__name__}:{caught}"
                        elapsed_wall, elapsed_cpu = (
                            time.perf_counter() - wall_started,
                            time.process_time() - cpu_started,
                        )
                        if error is None:
                            try:
                                validate(scene, result)
                                result = score_result(scene, result, reference)
                                validate(scene, result)
                            except Exception as caught:
                                error = f"validation_error:{type(caught).__name__}:{caught}"
                        if scenario_id(scene) != digest:
                            raise RuntimeError("Algorithm mutated the shared scenario")
                        row = _row(
                            name, seed, solver, scene, result, error, elapsed_cpu, elapsed_wall
                        )
                        rows.append(row)
                        if writer is None:
                            writer = csv.DictWriter(
                                csv_file, fieldnames=list(row), lineterminator="\n"
                            )
                            writer.writeheader()
                        writer.writerow(row)
                        csv_file.flush()
                        detail = dict(
                            scenario=name,
                            seed=seed,
                            solver=solver,
                            scenario_sha256=digest,
                            error=error,
                            execution_diagnostics=result.get("diagnostics", {}),
                            **_decision_summary(result),
                        )
                        diagnostics.write(_canonical(detail) + "\n")
                        diagnostics.flush()
                        if seed == protocol["seeds"][0]:
                            archive = pack_scene(
                                scene,
                                dict(
                                    scenario=name,
                                    seed=seed,
                                    solver=solver,
                                    params=protocol["solvers"][solver],
                                ),
                                result if result else None,
                            )
                            archive["experiment_audit"] = dict(
                                execution_valid=error is None, error=error
                            )
                            write_json(root / "traces" / f"{name}-{solver}.json", archive)
                            trace_count += 1
                    print(f"{name} seed={seed} {len(names)} runs recorded", flush=True)
        final_sources = source_hashes()
        if final_sources != sources:
            manifest.update(status="source_changed", final_source_hashes=final_sources)
            raise RuntimeError("Source changed during BCRD experiment; results cannot be finalized")
        summary = summarize(rows, protocol)
        write_json(root / "summary.json", summary)
        artifact_hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        }
        manifest.update(
            status="complete",
            recorded_runs=len(rows),
            comparable_runs=sum(row["comparison_valid"] for row in rows),
            execution_failures=sum(
                not row["execution_valid"] or not row["feasible"] for row in rows
            ),
            representative_traces=trace_count,
            artifact_hashes=artifact_hashes,
        )
        write_json(root / "manifest.json", manifest, overwrite=True)
        return rows, summary
    except Exception as caught:
        if manifest["status"] == "running":
            manifest.update(status="interrupted", error=f"{type(caught).__name__}:{caught}")
        manifest["recorded_runs"] = len(rows)
        write_json(root / "manifest.json", manifest, overwrite=True)
        raise


def run_development(output, seeds=tuple(range(10, 20)), *, configs=None, solvers=None):
    protocol = dict(
        schema=PROTOCOL_SCHEMA,
        split="development",
        frozen=False,
        seeds=list(seeds),
        configs=CONFIGS if configs is None else configs,
        solvers=DEFAULT_SOLVERS if solvers is None else solvers,
        baseline="G0",
        bootstrap=dict(resamples=4000, seed=20261016),
    )
    return _run(output, protocol)


def run_frozen(output, protocol):
    path = Path(protocol)
    raw = path.read_bytes()
    values = json.loads(raw.decode("utf-8-sig"))
    validate_protocol(values, require_frozen=True)
    return _run(output, values, protocol_bytes=raw)


def run_benchmark(output, split="development", protocol=None):
    if split not in SPLIT_RANGES:
        raise ValueError("Unknown split")
    if split == "development":
        if protocol is not None:
            raise ValueError("Use run_development for custom development parameters")
        return run_development(output)
    if protocol is None:
        raise ValueError("Formal evaluation requires a pre-frozen protocol file")
    values = json.loads(Path(protocol).read_text(encoding="utf-8-sig"))
    if values.get("split") != split:
        raise ValueError("Requested split differs from frozen protocol")
    return run_frozen(output, protocol)


def read_rows(path):
    """Read our CSV losslessly enough for independent summary reconstruction."""
    booleans = {"joint", "execution_valid", "feasible", "comparison_valid", "score_valid"}
    strings = {"scenario", "solver", "scenario_sha256", "backend", "reason"}
    rows = []
    with Path(path).open(encoding="utf-8", newline="") as file:
        for raw in csv.DictReader(file):
            row = {}
            for key, value in raw.items():
                if key in booleans:
                    if value not in ("True", "False"):
                        raise ValueError("Invalid CSV boolean")
                    row[key] = value == "True"
                elif key in strings:
                    row[key] = value or None if key == "reason" else value
                else:
                    row[key] = None if value == "" else json.loads(value)
            rows.append(row)
    return rows
