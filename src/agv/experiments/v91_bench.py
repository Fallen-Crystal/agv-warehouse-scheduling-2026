"""Frozen, paired V9.1 experiments on synthetic mixed warehouse templates.

Only registry.run_raw execution is timed. The historical A* reference is used
only by offline scoring, never as the paired dispatch control. Failed runs stay
in the matrix, and LF-normalized source changes prevent finalization.
"""

import copy
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
from dataclasses import replace
from pathlib import Path

from agv.evaluation.objective import WEIGHTS, reference_context, score_result
from agv.evaluation.validation import validate
from agv.experiments.cache import ResultCache, cache_identity, default_cache_dir
from agv.io.scenes import pack_scene, scenario_id
from agv.io.storage import write_json
from agv.runner.batch import BatchTask, run_batch
from agv.warehouse.mixed import generate_current

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_SCHEMA = "agv-v91-protocol-v1"
RESULT_SCHEMA = "agv-v91-results-v1"
SPLIT_RANGES = {"development": (10, 19), "holdout": (200, 219)}
DEFAULT_MAPS = {
    size: {"size": size, "vehicles": 4} for size in ("medium", "large", "xlarge", "xxlarge")
}
DEFAULT_WORKLOADS = {
    "dense_static": {"mode": "static", "arrival": "batch", "task_count": 12},
    "sparse_uniform": {
        "mode": "dynamic",
        "arrival": "uniform",
        "task_count": 12,
        "release_scale": 20,
    },
    "shared_bursts": {
        "mode": "dynamic",
        "arrival": "burst",
        "task_count": 12,
        "delivery_pattern": "shared",
        "release_scale": 8,
    },
}
DEFAULT_SOLVERS = {
    "G0": "sipp_stream_dispatch",
    "G1": "sipp_stream_matching",
    "G2": "sipp_position_dispatch",
    "G3": "sipp_position_matching_dispatch",
    "G4": "sipp_position_delay_dispatch",
    "B0": "sipp_stream_bcrd",
    "B1": "sipp_stream_bcrd_tail",
}
METRICS = (
    "weighted_score",
    "makespan",
    "mean_flow_time",
    "moves",
    "p90_flow_time",
    "max_flow_time",
    "empty_moves",
    "traffic_wait_steps",
    "standby_steps",
    "cpu_seconds",
    "wall_seconds",
)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def protocol_id(protocol):
    return hashlib.sha256(_canonical(protocol).encode("utf-8")).hexdigest()


def source_hashes():
    """Hash all shipped source plus this verifier after normalizing text to LF."""
    paths = [
        p
        for p in (ROOT / "src/agv").rglob("*")
        if p.is_file() and p.suffix in (".py", ".json", ".js", ".html", ".css")
    ]
    verifier = ROOT / "scripts/verify_v91.py"
    if verifier.is_file():
        paths.append(verifier)
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(
            p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        ).hexdigest()
        for p in sorted(paths)
    }


def default_protocol(split="development"):
    low, high = SPLIT_RANGES[split]
    return copy.deepcopy(
        dict(
            schema=PROTOCOL_SCHEMA,
            split=split,
            frozen=split == "holdout",
            seeds=list(range(low, min(high, 12) + 1))
            if split == "development"
            else list(range(low, high + 1)),
            maps=DEFAULT_MAPS,
            workloads=DEFAULT_WORKLOADS,
            solvers=DEFAULT_SOLVERS,
            baseline="G0",
            bootstrap={"resamples": 4000, "seed": 20261016},
            data_origin="Synthetic generate_current mixed-v9.1 templates; not a public real dataset",
            inference="Fixed-template paired bootstrap; no unseen-map or optimality guarantee",
        )
    )


def validate_protocol(protocol, *, require_frozen=False):
    from agv.registry import SOLVERS, STREAM_SOLVERS

    if not isinstance(protocol, dict) or protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("Unknown V9.1 protocol schema")
    split = protocol.get("split")
    if split not in SPLIT_RANGES:
        raise ValueError("Unknown V9.1 split")
    if (require_frozen or split == "holdout") and protocol.get("frozen") is not True:
        raise ValueError("Holdout requires a frozen protocol")
    seeds = protocol.get("seeds")
    low, high = SPLIT_RANGES[split]
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(type(s) is not int or not low <= s <= high for s in seeds)
        or len(seeds) != len(set(seeds))
    ):
        raise ValueError(f"{split} seeds must be unique integers in {low}..{high}")
    for field in ("maps", "workloads", "solvers"):
        values = protocol.get(field)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{field} must be a nonempty named mapping")
        for name, value in values.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError(f"Invalid {field} name")
            if field == "solvers":
                diagnostic_reference = value == "baseline" and protocol.get("stage") == "stage0"
                if not isinstance(value, str) or value not in SOLVERS:
                    raise ValueError(f"Unknown solver registry name: {value!r}")
                if not (
                    value == "sipp_stream_dispatch"
                    or value in STREAM_SOLVERS
                    or diagnostic_reference
                ):
                    raise ValueError("Paired solvers must name the V9.1 SIPP registry backend")
            elif not isinstance(value, dict) or set(value) & {"seed", "horizon"}:
                raise ValueError("Generator options cannot override protocol seed or horizon")
    for options in protocol["workloads"].values():
        scale = options.get("release_scale", 1)
        if type(scale) is not int or not 1 <= scale <= 100:
            raise ValueError("release_scale must be an integer in 1..100")
    baseline = protocol.get("baseline", "G0")
    if protocol["solvers"].get(baseline) != "sipp_stream_dispatch":
        raise ValueError("Paired baseline must be unchanged greedy+SIPP stream dispatch")
    if len(set(protocol["solvers"].values())) != len(protocol["solvers"]):
        raise ValueError("Solver registry names must be unique")
    boot = protocol.get("bootstrap", {})
    if (
        not isinstance(boot, dict)
        or type(boot.get("resamples")) is not int
        or not 100 <= boot["resamples"] <= 100000
        or type(boot.get("seed")) is not int
    ):
        raise ValueError("Invalid bootstrap protocol")
    _canonical(protocol)
    return protocol


def build_scene(map_options, workload, seed):
    """Apply release scaling after generation, including the publisher close time."""
    options = {**map_options, **workload}
    scale = options.pop("release_scale", 1)
    scene = generate_current(**options, seed=seed)
    if scale != 1:
        scene.tasks = [replace(task, release=task.release * scale) for task in scene.tasks]
        scene.order_stream_end *= scale
        scene.check()
    return scene


def _raw(name, scene):
    from agv.registry import run_raw

    return run_raw(name, scene)


def _bounds(scene):
    from agv.evaluation.bounds import lower_bounds

    return lower_bounds(scene)


def _interval(values, boot):
    if not values:
        return None
    rng = random.Random(boot["seed"])
    if all(value == values[0] for value in values):
        return [values[0], values[0]]
    samples = sorted(
        sum(rng.choices(values, k=len(values))) / len(values) for _ in range(boot["resamples"])
    )
    return [
        samples[math.floor(0.025 * (len(samples) - 1))],
        samples[math.ceil(0.975 * (len(samples) - 1))],
    ]


def summarize(rows, protocol):
    """Report paired instance effects with failures explicit for every metric."""
    baseline = protocol.get("baseline", "G0")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate experiment rows")
    templates = [f"{m}__{w}" for m in protocol["maps"] for w in protocol["workloads"]]
    groups = []
    for template in templates + ["__all__"]:
        for solver in protocol["solvers"]:
            own = [
                r
                for r in rows
                if r["solver"] == solver and (template == "__all__" or r["scenario"] == template)
            ]
            pairs = []
            for row in own:
                other = index.get((row["scenario"], row["seed"], baseline))
                if other is None or other["scenario_sha256"] != row["scenario_sha256"]:
                    raise ValueError("Missing or mismatched paired input")
                if (
                    row["comparison_valid"]
                    and other["comparison_valid"]
                    and row["backend"] == other["backend"]
                ):
                    pairs.append((other, row))
            deltas = [b["weighted_score"] - a["weighted_score"] for a, b in pairs]
            group = dict(
                scenario=template,
                solver=solver,
                comparison_role=(
                    "score_reference_diagnostic"
                    if protocol["solvers"][solver] == "baseline"
                    else "same_sipp_control"
                ),
                runs=len(own),
                successes=sum(r["comparison_valid"] for r in own),
                execution_failures=sum(not r["execution_valid"] or not r["feasible"] for r in own),
                paired_successes=len(pairs),
                excluded_pairs=len(own) - len(pairs),
                score_wins=sum(v < -1e-12 for v in deltas),
                score_losses=sum(v > 1e-12 for v in deltas),
                score_ties=sum(abs(v) <= 1e-12 for v in deltas),
                p90_degradations=sum(b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs),
                max_response_degradations=sum(
                    b["max_flow_time"] > a["max_flow_time"] for a, b in pairs
                ),
            )
            for metric in METRICS:
                values = [b[metric] for _, b in pairs]
                effects = [
                    100 * (a[metric] - b[metric]) / a[metric] for a, b in pairs if a[metric] > 0
                ]
                group[metric + "_mean_paired"] = statistics.mean(values) if values else None
                group[metric + "_improvement_pct_mean"] = (
                    statistics.mean(effects) if effects else None
                )
                group[metric + "_improvement_pct_95ci"] = _interval(effects, protocol["bootstrap"])
                group[metric + "_effect_pairs"] = len(effects)
            group["paired_F_improvement_pct_mean"] = group["weighted_score_improvement_pct_mean"]
            group["paired_F_improvement_pct_95ci"] = group["weighted_score_improvement_pct_95ci"]
            group["paired_F_difference_mean"] = statistics.mean(deltas) if deltas else None
            group["cpu_seconds_mean_all_runs"] = (
                statistics.mean(r["cpu_seconds"] for r in own) if own else None
            )
            ratios = [b["cpu_seconds"] / a["cpu_seconds"] for a, b in pairs if a["cpu_seconds"] > 0]
            group["cpu_ratio_mean"] = statistics.mean(ratios) if ratios else None
            groups.append(group)
    equal = []
    for solver in protocol["solvers"]:
        values = [
            g["paired_F_improvement_pct_mean"]
            for g in groups
            if g["solver"] == solver
            and g["scenario"] != "__all__"
            and g["paired_F_improvement_pct_mean"] is not None
        ]
        equal.append(
            dict(
                solver=solver,
                included_templates=len(values),
                total_templates=len(templates),
                template_equal_F_improvement_pct_mean=(statistics.mean(values) if values else None),
            )
        )
    return dict(
        baseline=baseline,
        groups=groups,
        template_equal=equal,
        bootstrap=protocol["bootstrap"],
        data_origin="Synthetic mixed-v9.1 map/workload templates",
        pairing="same scenario SHA and seed; registry raw SIPP dispatch only",
        score_direction="Lower F/T/R/D/P90/empty/trafficwait/CPU is better; standby is descriptive",
        uncertainty="Percentile bootstrap of paired instance effects on fixed templates; failures excluded explicitly; no selection correction or new-map guarantee",
        overall_aggregation="__all__: equal weight per valid pair; template_equal: equal weight per represented map/workload template",
    )


def _row(
    template,
    map_name,
    workload,
    seed,
    solver,
    registry_name,
    scene,
    result,
    error,
    cpu,
    wall,
    bounds,
    reference,
):
    complete = result.get("completed", 0)
    feasible = bool(
        result.get("feasible") and result.get("comparison_valid") and complete == len(scene.tasks)
    )
    comparable = bool(error is None and feasible and result.get("score_valid"))
    routing = result.get("routing_stats", {})
    row = dict(
        scenario=template,
        map=map_name,
        workload=workload,
        seed=seed,
        solver=solver,
        registry_name=registry_name,
        scenario_sha256=scenario_id(scene),
        backend="astar" if registry_name == "baseline" else "sipp",
        joint=False,
        execution_valid=error is None,
        feasible=feasible,
        comparison_valid=comparable,
        score_valid=comparable,
        completed=complete,
        total_tasks=len(scene.tasks),
        completion_rate=complete / len(scene.tasks) if scene.tasks else 1,
        reason=error or result.get("reason"),
        cpu_seconds=cpu,
        wall_seconds=wall,
        route_calls=routing.get("calls", 0),
        expanded=routing.get("expanded", 0),
    )
    for key in METRICS:
        if key not in ("cpu_seconds", "wall_seconds"):
            row[key] = result.get(key) if comparable else None
    for key, metric in (("T", "makespan"), ("R", "mean_flow_time"), ("D", "moves")):
        bound = bounds[key]
        row[key + "_lower_bound"] = bound
        row[key + "_gap_pct"] = (
            100 * (row[metric] / bound - 1) if comparable and bound > 0 else None
        )
    for key, field in (("T", "time"), ("R", "response"), ("D", "distance")):
        row["reference_" + key] = reference.get(field)
    row["F_lower_bound"] = (
        sum(
            WEIGHTS[field] * bounds[key] / reference[field]
            for key, field in (("T", "time"), ("R", "response"), ("D", "distance"))
        )
        if reference.get("available") and scene.tasks
        else 0.0
        if reference.get("available")
        else None
    )
    row["F_gap_pct"] = (
        100 * (row["weighted_score"] / row["F_lower_bound"] - 1)
        if comparable and row["F_lower_bound"] and row["F_lower_bound"] > 0
        else None
    )
    return row


class SourceChanged(RuntimeError):
    """A worker or coordinator detected a different measured implementation."""


def _check_sources(expected):
    if source_hashes() != expected:
        raise SourceChanged("Source changed during V9.1 experiment")


def _check_result_bounds(scene, result, bounds):
    """Only completed independently validated executions can test a lower bound."""
    if not (
        result.get("feasible")
        and result.get("comparison_valid")
        and result.get("completed") == len(scene.tasks)
    ):
        return
    for key, metric in (("T", "makespan"), ("R", "mean_flow_time"), ("D", "moves")):
        bound = bounds[key]
        if (
            type(bound) not in (int, float)
            or not math.isfinite(bound)
            or bound < 0
            or bound > result[metric] + 1e-9
        ):
            raise ValueError(
                f"{key} lower bound {bound!r} exceeds valid {metric}={result[metric]!r}"
            )


def _run_instance(job):
    """One isolated scene is the process-pool unit; only raw code is timed."""
    from agv.registry import SOLVERS

    protocol, map_name, workload, seed, position, sources, cache_settings = job
    _check_sources(sources)
    template = f"{map_name}__{workload}"
    scene = build_scene(protocol["maps"][map_name], protocol["workloads"][workload], seed)
    digest = scenario_id(scene)
    reference, bounds = reference_context(scene), _bounds(scene)
    names = list(protocol["solvers"])
    offset = position % len(names)
    rows, diagnostics, traces, pending_cache = [], [], [], []
    cache = ResultCache(cache_settings["directory"]) if cache_settings["directory"] else None
    for solver in names[offset:] + names[:offset]:
        registry_name = protocol["solvers"][solver]
        result, error = {}, None
        identity = cache_identity(
            scene,
            SOLVERS[registry_name],
            seed,
            dict(
                map=map_name,
                map_options=protocol["maps"][map_name],
                workload=workload,
                workload_options=protocol["workloads"][workload],
                registry_name=registry_name,
                protocol_schema=protocol["schema"],
            ),
            sources,
            resources={
                name: digest for name, digest in sources.items() if Path(name).suffix != ".py"
            },
        )

        def check_cached(payload):
            if not isinstance(payload["result"], dict) or any(
                type(payload[field]) not in (int, float)
                or not math.isfinite(payload[field])
                or payload[field] < 0
                for field in ("cpu_seconds", "wall_seconds")
            ):
                raise ValueError("Invalid cached execution or timing")
            environment = payload["measurement_environment"]
            if (
                not isinstance(environment, dict)
                or set(environment) != {"platform", "processor", "machine", "python", "workers"}
                or any(
                    not isinstance(environment[field], str) or not environment[field]
                    for field in ("platform", "processor", "machine", "python")
                )
                or environment["python"] != platform.python_version()
                or type(environment["workers"]) is not int
                or not 1 <= environment["workers"] <= 32
            ):
                raise ValueError("Invalid original measurement environment")
            validate(scene, payload["result"])
            _check_result_bounds(scene, payload["result"], bounds)

        cached, cache_status = None, "disabled" if cache is None else "refresh"
        if cache is not None and not cache_settings["refresh"]:
            cached, cache_status = cache.load(identity, check_cached)
        if cached is not None:
            result, cpu, wall = cached["result"], cached["cpu_seconds"], cached["wall_seconds"]
            environment = cached["measurement_environment"]
        else:
            environment = dict(
                platform=platform.platform(),
                processor=platform.processor() or "unknown",
                machine=platform.machine() or "unknown",
                python=platform.python_version(),
                workers=cache_settings["workers"],
            )
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            try:
                result = _raw(registry_name, scene)
                if not isinstance(result, dict):
                    raise TypeError("Raw solver must return a result mapping")
            except Exception as caught:
                result = result if isinstance(result, dict) else {}
                error = f"algorithm_error:{type(caught).__name__}:{caught}"
            wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
        if error is None:
            try:
                validate(scene, result)
            except Exception as caught:
                error = f"validation_error:{type(caught).__name__}:{caught}"
        if error is None:
            try:
                _check_result_bounds(scene, result, bounds)
            except Exception as caught:
                error = f"bound_error:{type(caught).__name__}:{caught}"
        if error is None:
            try:
                result = score_result(scene, result, reference)
                validate(scene, result)
            except Exception as caught:
                error = f"validation_error:{type(caught).__name__}:{caught}"
        if scenario_id(scene) != digest:
            raise RuntimeError("Algorithm mutated the shared scenario")
        if cache is not None and cached is None and error is None:
            pending_cache.append(
                (
                    identity,
                    dict(
                        result=result,
                        cpu_seconds=cpu,
                        wall_seconds=wall,
                        measurement_environment=environment,
                    ),
                )
            )
        rows.append(
            _row(
                template,
                map_name,
                workload,
                seed,
                solver,
                registry_name,
                scene,
                result,
                error,
                cpu,
                wall,
                bounds,
                reference,
            )
        )
        rows[-1].update(
            cache_status=cache_status,
            timing_origin="cached" if cached is not None else "fresh",
            measurement_environment=_canonical(environment),
        )
        diagnostics.append(
            dict(
                scenario=template,
                seed=seed,
                solver=solver,
                scenario_sha256=digest,
                error=error,
                measurement_environment=environment,
                dispatch_stats=result.get("dispatch_stats", {}),
                diagnostics=result.get("diagnostics", {}),
            )
        )
        if seed == protocol["seeds"][0]:
            archive = pack_scene(
                scene,
                dict(
                    scenario=template,
                    map=map_name,
                    workload=workload,
                    seed=seed,
                    solver=solver,
                    registry_name=registry_name,
                ),
                result or None,
            )
            archive["experiment_audit"] = dict(execution_valid=error is None, error=error)
            archive["lower_bounds"] = bounds
            traces.append((f"{template}-{solver}.json", archive))
    _check_sources(sources)
    for identity, payload in pending_cache:
        cache.store(identity, payload)
    evidence = dict(scenario=template, seed=seed, scenario_sha256=digest, bounds=bounds)
    return rows, diagnostics, traces, evidence


def run_benchmark(
    output, protocol=None, workers=1, *, cache_dir=None, no_cache=False, refresh=False
):
    """Run a dict/path protocol; process workers operate on whole paired scenes.

    Rows are written in canonical protocol-instance order and rotated solver
    order regardless of worker completion order. Worker process CPU excludes
    peers; wall times and CPU contention remain descriptive measurements.
    """
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError("workers must be an integer in 1..32")
    if no_cache and refresh:
        raise ValueError("no_cache and refresh cannot be combined")
    cache_path = Path(cache_dir or default_cache_dir()).resolve()
    if not no_cache and cache_path.is_relative_to(ROOT / "src/agv"):
        raise ValueError("Experiment caches must be outside shipped source")
    if protocol is None:
        protocol = default_protocol()
    if isinstance(protocol, (str, Path)):
        raw = Path(protocol).read_bytes()
        protocol = json.loads(raw.decode("utf-8-sig"))
    else:
        protocol = copy.deepcopy(protocol)
        raw = (json.dumps(protocol, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    validate_protocol(protocol)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    (root / "protocol.json").write_bytes(raw)
    sources = source_hashes()
    cache_settings = dict(
        directory=None if no_cache else str(cache_path), refresh=refresh, workers=workers
    )
    manifest = dict(
        schema=RESULT_SCHEMA,
        status="running",
        split=protocol["split"],
        protocol_sha256=protocol_id(protocol),
        protocol_file_sha256=hashlib.sha256(raw).hexdigest(),
        source_hashes=sources,
        source_hash_mode="utf8-text-LF-normalized-sha256",
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        python=platform.python_version(),
        platform=platform.platform(),
        workers=workers,
        cache=cache_settings,
        expected_runs=(
            len(protocol["maps"])
            * len(protocol["workloads"])
            * len(protocol["seeds"])
            * len(protocol["solvers"])
        ),
        data_origin="Synthetic generate_current scenarios, not a public real dataset",
        timing="Raw execution process_time/perf_counter excludes validation, bounds and A* reference. timing_origin=cached preserves the original measured CPU/wall, not a fresh measurement; use --no-cache for timing comparisons. Concurrent workers compete for machine resources.",
        ordering="protocol maps, workloads and seeds; solver order rotates by seed position; independent of worker completion order",
        notes="First-seed traces are representative, not a performance sample. Failures remain in CSV. Stage0 A0 is an A* score-reference diagnostic, excluded from same-SIPP paired effects.",
    )
    write_json(root / "manifest.json", manifest)
    jobs = [
        BatchTask(seed, (protocol, m, w, seed, position, sources, cache_settings))
        for m in protocol["maps"]
        for w in protocol["workloads"]
        for position, seed in enumerate(protocol["seeds"])
    ]
    rows, traces = [], 0
    try:
        results = run_batch(jobs, _run_instance, workers=workers)
        with (
            (root / "runs.csv").open("x", encoding="utf-8", newline="") as file,
            (root / "diagnostics.jsonl").open("x", encoding="utf-8", newline="\n") as diagnostics,
            (root / "bounds.jsonl").open("x", encoding="utf-8", newline="\n") as bound_file,
        ):
            writer = None
            for instance_rows, details, archives, bounds in results:
                _check_sources(sources)
                for row in instance_rows:
                    if writer is None:
                        writer = csv.DictWriter(file, fieldnames=list(row), lineterminator="\n")
                        writer.writeheader()
                    writer.writerow(row)
                    rows.append(row)
                file.flush()
                for detail in details:
                    diagnostics.write(_canonical(detail) + "\n")
                diagnostics.flush()
                bound_file.write(_canonical(bounds) + "\n")
                bound_file.flush()
                for name, archive in archives:
                    write_json(root / "traces" / name, archive)
                    traces += 1
                print(
                    f"{bounds['scenario']} seed={bounds['seed']}: {len(instance_rows)} runs recorded",
                    flush=True,
                )
        _check_sources(sources)
        summary = summarize(rows, protocol)
        cache_report = dict(
            hits=sum(r["cache_status"] == "hit" for r in rows),
            misses=sum(r["cache_status"] == "miss" for r in rows),
            invalid=sum(r["cache_status"] == "invalid" for r in rows),
            refreshed=sum(r["cache_status"] == "refresh" for r in rows),
            disabled=sum(r["cache_status"] == "disabled" for r in rows),
            timing="CPU/wall for cached rows are historical; no new solver execution was timed",
        )
        cache_report["hit_rate"] = cache_report["hits"] / len(rows) if rows else 0.0
        summary["cache"] = cache_report
        write_json(root / "summary.json", summary)
        artifacts = {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != "manifest.json"
        }
        manifest.update(
            status="complete",
            recorded_runs=len(rows),
            comparable_runs=sum(r["comparison_valid"] for r in rows),
            execution_failures=sum(not r["execution_valid"] or not r["feasible"] for r in rows),
            representative_traces=traces,
            artifact_hashes=artifacts,
            cache_report=cache_report,
        )
        write_json(root / "manifest.json", manifest, overwrite=True)
        return rows, summary
    except Exception as caught:
        if isinstance(caught, SourceChanged):
            manifest.update(status="source_changed", error=str(caught))
        elif manifest["status"] == "running":
            manifest.update(status="interrupted", error=f"{type(caught).__name__}:{caught}")
        manifest["recorded_runs"] = len(rows)
        write_json(root / "manifest.json", manifest, overwrite=True)
        raise
    finally:
        results.close()


def read_rows(path):
    booleans = {"joint", "execution_valid", "feasible", "comparison_valid", "score_valid"}
    strings = {
        "scenario",
        "map",
        "workload",
        "solver",
        "registry_name",
        "scenario_sha256",
        "backend",
        "reason",
        "cache_status",
        "timing_origin",
        "measurement_environment",
    }
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
                    row[key] = (value or None) if key == "reason" else value
                else:
                    row[key] = None if value == "" else json.loads(value)
            rows.append(row)
    return rows
