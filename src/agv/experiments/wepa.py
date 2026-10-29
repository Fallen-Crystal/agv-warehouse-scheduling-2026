"""Installed WEPA runs and frozen, window-paired experiments.

The old ZIP remains historical evidence. This module measures the ordinary
package source under its own identity and never re-signs an archived result.
"""

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from importlib.resources import files
from pathlib import Path

from agv.core.objectives import LinearObjective
from agv.data.wepa import build
from agv.evaluation.objectives.linear_f import checked_score
from agv.experiments.cache import ResultCache, cache_key
from agv.io.storage import write_json
from agv.policy.wepa import PROFILES
from agv.runner import BatchTask, run_batch

ARCHIVE_SHA256 = "3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b"
RESOURCE = files("agv.data.wepa").joinpath("resources")


def reference_protocol():
    return json.loads(RESOURCE.joinpath("protocol.json").read_text(encoding="utf-8"))


def source_identity():
    package = Path(__file__).resolve().parents[1]
    return {
        path.relative_to(package).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        ).hexdigest()
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix in (".py", ".json", ".js", ".html", ".css")
    }


def execute_case(case, method, seed, *, configuration=None, objective=None, latency=None):
    """Return a detached complete trace; only the raw runner is timed."""
    from agv.runner.wepa import run

    if method not in PROFILES and method not in ("eta", "fcfs"):
        raise ValueError("Unknown WEPA algorithm")
    if type(seed) is not int or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    configuration = configuration or reference_protocol()["configuration"]
    objective = objective or LinearObjective(vehicles=configuration["vehicles"])
    model = build(case, **configuration)
    cpu, wall = time.process_time(), time.perf_counter()
    options = {} if latency is None else dict(latency=latency)
    result = run(model, method, seed, objective=objective, **options)
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
    try:
        score = checked_score(model, result, objective)
    except ValueError as error:
        score = dict(
            audit=dict(valid=False, error=str(error)), F_linear_v2=None, J_equivalent_seconds=None
        )
    row = dict(
        case=case["case"],
        profile=method,
        seed=seed,
        valid=bool(result["valid"] and score["audit"]["valid"]),
        cpu=cpu,
        wall=wall,
        **{key: result[key] for key in ("T", "R", "D", "p90", "empty_distance", "traffic_wait")},
        F=score["F_linear_v2"],
        J=score["J_equivalent_seconds"],
        tasks=len(case["tasks"]),
        objective_sha256=objective.fingerprint,
    )
    return dict(
        row=row,
        case=case,
        result=result,
        scoring=score,
        objective_id=objective.objective_id,
        model_profile="wepa",
        geometry_source="reviewed-mixed-grid-with-inbound-terminals",
        archive_source_sha256=ARCHIVE_SHA256,
    )


def run_case(case_id, method, seed, output, *, overwrite=False, latency=None):
    if Path(output).exists() and not overwrite:
        raise ValueError("Refuse to overwrite an experiment")
    protocol = reference_protocol()
    case = next((case for case in protocol["cases"] if case["case"] == case_id), None)
    if case is None:
        raise ValueError(f"Unknown WEPA case: {case_id}")
    sources = source_identity()
    trace = execute_case(
        case,
        method,
        seed,
        configuration=protocol["configuration"],
        objective=LinearObjective(**protocol["objective"]),
        latency=latency,
    )
    if source_identity() != sources:
        raise ValueError("Implementation changed during execution")
    trace.update(
        implementation_sha256=sources,
        config=dict(case=case_id, profile=method, seed=seed, output=str(output)),
    )
    write_json(output, trace, overwrite=overwrite)
    return trace


def freeze_protocol(config, output):
    """Bind settings, objective, source and disjoint windows before any run."""
    required = {
        "configuration",
        "objective",
        "cases",
        "development",
        "validation",
        "sealed",
        "methods",
        "seeds",
        "baseline",
        "timeout_seconds",
    }
    if not required <= set(config) or set(config) - required - {"input_audit"}:
        raise ValueError(f"Protocol needs exactly {sorted(required)}")
    ids = [case["case"] for case in config["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate input window")
    splits = [config[name] for name in ("development", "validation", "sealed")]
    flat = [case for split in splits for case in split]
    if len(flat) != len(set(flat)) or set(flat) != set(ids) or not splits[0]:
        raise ValueError("Windows must form disjoint development/validation/sealed partitions")
    if config["baseline"] not in config["methods"] or len(set(config["methods"])) != len(
        config["methods"]
    ):
        raise ValueError("Unique methods including the control are required")
    if any(
        method not in PROFILES and method not in ("eta", "fcfs") for method in config["methods"]
    ):
        raise ValueError("Unknown method")
    if (
        not config["seeds"]
        or len(set(config["seeds"])) != len(config["seeds"])
        or any(type(seed) is not int or seed < 0 for seed in config["seeds"])
    ):
        raise ValueError("Unique nonnegative seeds required")
    if (
        type(config["timeout_seconds"]) not in (int, float)
        or not 0 < config["timeout_seconds"] <= 3600
    ):
        raise ValueError("Timeout must be positive and at most one hour")
    objective = LinearObjective(**config["objective"])
    if objective.vehicles != config["configuration"]["vehicles"]:
        raise ValueError("Objective and model fleets differ")
    frozen = dict(
        schema="agv-wepa-protocol-v1",
        config=config,
        sources=source_identity(),
        objective_id=objective.objective_id,
    )
    frozen["protocol_sha256"] = cache_key(frozen)
    write_json(output, frozen)
    return frozen


def load_protocol(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = value.get("protocol_sha256")
    if (
        value.get("schema") != "agv-wepa-protocol-v1"
        or cache_key({k: v for k, v in value.items() if k != "protocol_sha256"}) != expected
    ):
        raise ValueError("Protocol identity differs")
    if value["sources"] != source_identity():
        raise ValueError("Source differs from frozen protocol")
    return value


def audit_trace(trace, frozen):
    config = frozen["config"]
    declared = next((c for c in config["cases"] if c["case"] == trace["row"]["case"]), None)
    if (
        trace.get("objective_id") != frozen["objective_id"]
        or trace.get("implementation_sha256") != frozen["sources"]
        or trace.get("protocol_sha256") != frozen["protocol_sha256"]
        or declared != trace["case"]
    ):
        raise ValueError("Trace input, objective or implementation identity differs")
    score = checked_score(
        build(declared, **config["configuration"]),
        trace["result"],
        LinearObjective(**config["objective"]),
    )
    if score != trace["scoring"] or trace["row"]["F"] != score["F_linear_v2"]:
        raise ValueError("Stored result does not match independent scoring")


def _trial(payload):
    """A real wall deadline bounds both solver work and independent checking."""
    protocol, case_id, method, seed, output, cache_dir = payload
    target = Path(output)
    command = [
        sys.executable,
        "-m",
        "agv.experiments.wepa",
        "trial",
        "--protocol",
        protocol,
        "--case",
        case_id,
        "--algorithm",
        method,
        "--seed",
        str(seed),
        "--output",
        output,
    ]
    frozen = load_protocol(protocol)
    limit = frozen["config"]["timeout_seconds"]
    cache = ResultCache(cache_dir) if cache_dir else None
    identity = dict(
        protocol_sha256=frozen["protocol_sha256"],
        objective_id=frozen["objective_id"],
        source_hashes=frozen["sources"],
        case=case_id,
        method=method,
        seed=seed,
    )
    try:
        status = "disabled"
        if cache:
            trace, status = cache.load(identity, lambda value: audit_trace(value, frozen))
            if trace is not None:
                write_json(target, trace)
                return dict(
                    **trace["row"],
                    status="complete",
                    trace=output,
                    cache_status="hit",
                    timing_origin="stored_raw_execution",
                )
        process = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=limit, check=False
        )
        if process.returncode:
            raise ValueError(process.stderr[-4000:])
        trace = json.loads(target.read_text(encoding="utf-8"))
        audit_trace(trace, frozen)
        if cache:
            cache.store(identity, trace)
        return dict(
            **trace["row"],
            status="complete",
            trace=output,
            cache_status=status,
            timing_origin="fresh_raw_execution",
        )
    except (subprocess.TimeoutExpired, ValueError, OSError) as error:
        return dict(
            case=case_id,
            profile=method,
            seed=seed,
            status="failed",
            valid=False,
            error=f"{type(error).__name__}: {error}",
            trace=output,
            F=None,
            cpu=None,
        )


def benchmark(protocol_path, split, output, *, workers=1, cache_dir=None):
    protocol_path = str(Path(protocol_path).resolve())
    frozen = load_protocol(protocol_path)
    if split not in ("development", "validation"):
        raise ValueError("The final sealed set cannot be opened by routine experiments")
    output = Path(output).resolve()
    config = frozen["config"]
    methods = config["methods"]
    selection_record = None
    if split == "validation":
        selection = output.parent / "selection.json"
        if (
            not selection.exists()
            or json.loads(selection.read_text())["protocol_sha256"] != frozen["protocol_sha256"]
        ):
            raise ValueError("Validation requires a frozen development selection")
        selection_record = json.loads(selection.read_text(encoding="utf-8"))
        methods = list(dict.fromkeys((config["baseline"], selection_record["selected"])))
        if any(method not in config["methods"] for method in methods):
            raise ValueError("Selection is not part of declared methods")
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for case in config[split]:
        for method in methods:
            for seed in config["seeds"]:
                target = str(output / f"{case}--{method}--s{seed}.json")
                tasks.append(
                    BatchTask(
                        seed,
                        (
                            protocol_path,
                            case,
                            method,
                            seed,
                            target,
                            str(Path(cache_dir).resolve()) if cache_dir else None,
                        ),
                    )
                )
    rows = []
    for row in run_batch(tasks, _trial, workers=workers):
        rows.append(row)
        write_json(
            output / "runs.json",
            dict(
                protocol_sha256=frozen["protocol_sha256"],
                objective_id=frozen["objective_id"],
                split=split,
                methods=methods,
                selection=selection_record,
                rows=rows,
                complete=len(rows) == len(tasks),
            ),
            overwrite=True,
        )
    if load_protocol(protocol_path) != frozen:
        raise ValueError("Source/protocol changed during measurement")
    return rows


def select(protocol_path, development, output):
    frozen = load_protocol(protocol_path)
    data = json.loads(Path(development).read_text(encoding="utf-8"))
    if (
        data["protocol_sha256"] != frozen["protocol_sha256"]
        or data["objective_id"] != frozen["objective_id"]
        or data["split"] != "development"
        or not data["complete"]
    ):
        raise ValueError("Selection requires a complete matching development phase")
    if (Path(output).parent / "validation").exists():
        raise ValueError("Selection must precede validation")
    config, rows = frozen["config"], data["rows"]
    expected = {
        (c, m, s) for c in config["development"] for m in config["methods"] for s in config["seeds"]
    }
    if (
        len(rows) != len(expected)
        or {(r["case"], r["profile"], r["seed"]) for r in rows} != expected
    ):
        raise ValueError("Missing or duplicate development rows")
    for row in rows:
        if row["valid"]:
            trace = json.loads(Path(row["trace"]).read_text(encoding="utf-8"))
            audit_trace(trace, frozen)
            if any(row.get(k) != trace["row"].get(k) for k in trace["row"]):
                raise ValueError("Selection rows differ from audited traces")
    ranked = []
    for method in config["methods"]:
        sample = [row for row in rows if row["profile"] == method]
        if not all(row["valid"] for row in sample):
            continue
        # Windows, rather than repeated random seeds, are the independent units.
        ranked.append(
            dict(
                method=method,
                F=statistics.mean(
                    statistics.mean(r["F"] for r in sample if r["case"] == case)
                    for case in config["development"]
                ),
                cpu=statistics.mean(r["cpu"] for r in sample),
            )
        )
    if not ranked:
        raise ValueError("No complete valid method")
    ranked.sort(key=lambda row: (row["F"], row["cpu"], row["method"]))
    value = dict(
        protocol_sha256=frozen["protocol_sha256"],
        objective_id=frozen["objective_id"],
        selected=ranked[0]["method"],
        ranked=ranked,
        validation_read=False,
    )
    write_json(output, value)
    return value


def analyze(protocol_path, input_path, output):
    frozen = load_protocol(protocol_path)
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if (
        data["objective_id"] != frozen["objective_id"]
        or data["protocol_sha256"] != frozen["protocol_sha256"]
    ):
        raise ValueError("Cannot compare different objective/source/protocol identities")
    if not data["complete"]:
        raise ValueError("An incomplete phase cannot establish an algorithm improvement")
    config, rows = frozen["config"], data["rows"]
    cases = config[data["split"]]
    methods = data["methods"]
    if len(set(methods)) != len(methods) or any(m not in config["methods"] for m in methods):
        raise ValueError("Invalid phase methods")
    if data["split"] == "validation":
        choice = data["selection"]
        if choice["protocol_sha256"] != frozen["protocol_sha256"] or methods != list(
            dict.fromkeys((config["baseline"], choice["selected"]))
        ):
            raise ValueError("Validation methods differ from development selection")
    elif methods != config["methods"]:
        raise ValueError("Development methods differ from protocol")
    expected = {(c, m, s) for c in cases for m in methods for s in config["seeds"]}
    if (
        len(rows) != len(expected)
        or {(r["case"], r["profile"], r["seed"]) for r in rows} != expected
    ):
        raise ValueError("Unpaired or duplicated runs")
    # Re-audit cache/files instead of trusting a previously written valid label.
    for row in rows:
        if not row["valid"]:
            continue
        trace = json.loads(Path(row["trace"]).read_text(encoding="utf-8"))
        audit_trace(trace, frozen)
        if any(row.get(k) != trace["row"].get(k) for k in trace["row"]):
            raise ValueError("Aggregate row differs from the independently audited trace")
    from agv.experiments.v91_bench import _interval

    groups = {}
    for method in methods:
        pairs = []
        for case in cases:
            control = [r for r in rows if r["case"] == case and r["profile"] == config["baseline"]]
            candidate = [r for r in rows if r["case"] == case and r["profile"] == method]
            if not all(r["valid"] for r in control + candidate):
                continue
            base, new = (
                statistics.mean(r["F"] for r in control),
                statistics.mean(r["F"] for r in candidate),
            )
            pairs.append(
                dict(
                    case=case,
                    gain_percent=100 * (base - new) / base,
                    deltas={
                        key: statistics.mean(r[key] for r in candidate)
                        - statistics.mean(r[key] for r in control)
                        for key in (
                            "F",
                            "T",
                            "R",
                            "D",
                            "p90",
                            "empty_distance",
                            "traffic_wait",
                            "cpu",
                        )
                    },
                )
            )
        gains = [pair["gain_percent"] for pair in pairs]
        groups[method] = dict(
            pairs=pairs,
            expected_windows=len(cases),
            comparable_windows=len(pairs),
            failures=sum(not r["valid"] for r in rows if r["profile"] == method),
            mean_gain_percent=statistics.mean(gains) if gains else None,
            median_gain_percent=statistics.median(gains) if gains else None,
            bootstrap95=_interval(gains, {"resamples": 4000, "seed": 20261029})
            if len(gains) >= 4
            else None,
            improved=sum(x > 1e-10 for x in gains),
            worsened=sum(x < -1e-10 for x in gains),
        )
    report = dict(
        protocol_sha256=frozen["protocol_sha256"],
        objective_id=frozen["objective_id"],
        split=data["split"],
        groups=groups,
        inference="Paired windows; seeds are not independent observations; historical windows are not fresh holdout",
    )
    write_json(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("trial", "freeze", "run", "select", "analyze"))
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--algorithm", "--profile", dest="algorithm", default="gate")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args(argv)
    if args.action == "freeze" and args.input is None:
        parser.error("freeze requires --input")
    if args.action != "freeze" and args.protocol is None:
        parser.error("this action requires --protocol")
    if args.action in ("select", "analyze") and args.input is None:
        parser.error("this action requires --input")
    if args.action == "trial" and args.case is None:
        parser.error("trial requires --case")
    if args.action == "freeze":
        result = freeze_protocol(json.loads(args.input.read_text(encoding="utf-8")), args.output)
    elif args.action == "trial":
        frozen = load_protocol(args.protocol)
        config = frozen["config"]
        case = next((c for c in config["cases"] if c["case"] == args.case), None)
        if case is None:
            raise ValueError("Case not declared by the protocol")
        if args.algorithm not in config["methods"] or args.seed not in config["seeds"]:
            raise ValueError("Trial not declared by protocol")
        if args.case in config["sealed"]:
            raise ValueError("Sealed final windows are unavailable")
        result = execute_case(
            case,
            args.algorithm,
            args.seed,
            configuration=config["configuration"],
            objective=LinearObjective(**config["objective"]),
        )
        load_protocol(args.protocol)
        result.update(
            implementation_sha256=frozen["sources"], protocol_sha256=frozen["protocol_sha256"]
        )
        write_json(args.output, result)
    elif args.action == "run":
        result = benchmark(
            args.protocol, args.split, args.output, workers=args.workers, cache_dir=args.cache_dir
        )
    elif args.action == "select":
        result = select(args.protocol, args.input, args.output)
    else:
        result = analyze(args.protocol, args.input, args.output)
    print(
        json.dumps(
            result.get("row", result) if isinstance(result, dict) else dict(runs=len(result)),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
