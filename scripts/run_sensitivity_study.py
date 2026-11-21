"""Paired, source-frozen WEPA experiments; production defaults are untouched.

Prepare a recommended runtime first, then `init`, `run`, and `verify` a study.
Every subprocess independently validates its complete trajectory. Compact trial
records are shareable; compressed trajectories and logs stay in ignored runs/.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
MAIN = "ea719b598662707c67f9d93b990812d4e45e24cd"
ADAPTIVE = ROOT / "research/dqn-experiment-v2/adaptive_genetic.py"
METRICS = ("T", "R", "D", "p90", "empty_distance", "traffic_wait")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def variants():
    result = [
        dict(
            id=name,
            profile=name,
            overrides={},
            group="evolution",
            seeds=[0, 1] if name in ("fcfs", "eta", "hungarian") else list(range(5)),
        )
        for name in ("fcfs", "eta", "simple", "wide", "gate", "hga", "hungarian")
    ]
    for name, overrides in (
        ("gate_proxy96", dict(proxy=96)),
        ("gate_preview3", dict(previews=3)),
        ("gate_proxy96_preview3", dict(proxy=96, previews=3)),
        ("gate_gen8", dict(generations=8)),
    ):
        result.append(
            dict(id=name, profile="gate", overrides=overrides, group="budget", seeds=[0, 1, 2])
        )
    for mutation, crossover in ((False, False), (True, False), (False, True), (True, True)):
        result.append(
            dict(
                id=f"wide_adapt{int(mutation)}{int(crossover)}",
                profile="wide",
                overrides={},
                group="adaptive",
                seeds=[0, 1, 2],
                adaptive=dict(
                    adaptive_mutation=mutation,
                    adaptive_crossover=crossover,
                    mutation_rate=0.7,
                    crossover_rate=0.9,
                ),
            )
        )
    return result


def jobs(plan):
    result = []
    for variant in plan["variants"]:
        for case in plan["cases"]:
            for seed in variant.get("seeds", plan["seeds"]):
                result.append(
                    dict(
                        id=f"{case}__{variant['id']}__s{seed}",
                        case=case,
                        variant=variant["id"],
                        seed=seed,
                    )
                )
    return result


def initialize(study, runtime):
    study, runtime = Path(study).resolve(), Path(runtime).resolve()
    if study.exists():
        raise FileExistsError(study)
    manifest = read(runtime / "runtime_manifest.json")
    if manifest["main_commit"] != MAIN:
        raise ValueError("This plan is pinned to main ea719b5")
    protocol = read(runtime / "data/protocol.json")
    selected = [case for case in protocol["cases"] if case["case"] in protocol["development"]]
    sources = {
        "runner": sha(SCRIPT),
        "adaptive_operator": sha(ADAPTIVE),
        "runtime_manifest": sha(runtime / "runtime_manifest.json"),
    }
    comparisons = [
        ("wide", "simple"),
        ("gate", "wide"),
        ("hga", "gate"),
        ("hungarian", "gate"),
        ("gate", "eta"),
        ("gate", "fcfs"),
    ]
    comparisons += [(v["id"], "gate") for v in variants() if v["group"] == "budget"]
    comparisons += [(f"wide_adapt{code}", "wide_adapt00") for code in ("10", "01", "11")]
    comparisons += [("wide_adapt11", "wide")]
    plan = dict(
        study_id="wepa-multiseed-sensitivity-20261120-v2",
        created_utc=datetime.now(timezone.utc).isoformat(),
        base_commit=MAIN,
        runtime=str(runtime),
        trace_root=str(
            ROOT / "runs" / (study.name + "-" + digest(str(study))[:8]) / "trajectories"
        ),
        sources=sources,
        runtime_provenance=manifest,
        protocol_sha256=sha(runtime / "data/protocol.json"),
        objective=protocol["objective"],
        configuration=protocol["configuration"],
        cases=[c["case"] for c in selected],
        case_provenance={
            c["case"]: dict(source_day=c["source_day"], tasks=len(c["tasks"]), sha256=digest(c))
            for c in selected
        },
        seeds=list(range(5)),
        variants=variants(),
        comparisons=[dict(candidate=c, reference=r, label=f"{c} vs {r}") for c, r in comparisons],
        limits=dict(cpu_seconds=600, wall_seconds=900, max_workers=2),
        execution_order_seed=20261120,
        environment=dict(
            python=sys.version,
            platform=platform.platform(),
            machine=platform.machine(),
            executable=sys.executable,
        ),
        interpretation={
            "data_split": "All four windows are historical development data; retrospective, not unseen validation",
            "randomness": "eval_seed changes search, not independent physical scenarios; slot mapping seed is fixed at 17",
            "unit": "Average seeds within each source date, then weight dates equally; date bootstrap is descriptive with n=4",
            "adaptive": "Transfer of the later adaptive GA operator to the common wide-policy runtime; no DQN retraining or full historical-version reproduction",
            "comparison": "Same cases, fleet, rules, SIPP and linear physical objective; simple/wide changes a budget bundle",
            "adoption": "No automatic selection or default change from these development results",
            "preflight": "An initial 5/200 preflight batch was stopped for runner formatting and portability fixes, retained under ignored runs/sensitivity-20261120/aborted-preflight-study, excluded from this fresh full matrix; solver parameters and case selection were not tuned",
        },
    )
    order = jobs(plan)
    random.Random(plan["execution_order_seed"]).shuffle(order)
    plan["execution_order"] = [job["id"] for job in order]
    plan["expected_trials"] = len(order)
    write_new(study / "plan.json", plan)
    write_new(study / "freeze.json", dict(plan_sha256=sha(study / "plan.json"), sources=sources))
    print(json.dumps(dict(study=str(study), trials=len(order), cases=plan["cases"])))
    return plan


def check_sources(study):
    study = Path(study)
    plan, freeze = read(study / "plan.json"), read(study / "freeze.json")
    if sha(study / "plan.json") != freeze["plan_sha256"]:
        raise ValueError("Frozen plan changed")
    paths = dict(
        runner=SCRIPT,
        adaptive_operator=ADAPTIVE,
        runtime_manifest=Path(plan["runtime"]) / "runtime_manifest.json",
    )
    for key, path in paths.items():
        if sha(path) != freeze["sources"][key]:
            raise ValueError("Frozen source changed: " + key)
    for name, expected in plan["runtime_provenance"]["files"].items():
        if sha(Path(plan["runtime"]) / name) != expected:
            raise ValueError("Prepared runtime changed: " + name)
    return plan


def search_summary(result, settings, activity):
    searches = [r for r in result["search_log"] if "proxy_evaluations" in r]
    return dict(
        searches=len(searches),
        proxy_evaluations=sum(r["proxy_evaluations"] for r in searches),
        previews=sum(r["previews"] for r in searches),
        gate_decisions=sum(
            r.get("mode") == "immediate_batch_matching" for r in result["search_log"]
        ),
        proxy_cap_hits=sum(r["proxy_evaluations"] >= settings.get("proxy", 96) for r in searches),
        preview_cap_hits=sum(r["previews"] >= settings.get("previews", 3) for r in searches),
        improvements=sum(bool(r.get("changed")) for r in searches),
        operator_activity=activity,
    )


def worker(study, trial_id):
    study = Path(study).resolve()
    plan = check_sources(study)
    job = next(j for j in jobs(plan) if j["id"] == trial_id)
    variant = next(v for v in plan["variants"] if v["id"] == job["variant"])
    runtime = Path(plan["runtime"])
    sys.path.insert(0, str(runtime))
    # paths sets the frozen baseline/engine ahead of the installed application.
    paths = importlib.import_module("paths")
    import improved.policy
    import v2.policy
    from improved.execute import run
    from improved.profiles import PROFILES
    from objective import LinearObjective, checked_score
    from wepa.data import build

    paths.verify_baseline()
    protocol = read(runtime / "data/protocol.json")
    case = next(c for c in protocol["cases"] if c["case"] == job["case"])
    if digest(case) != plan["case_provenance"][job["case"]]["sha256"]:
        raise ValueError("Scenario changed")
    objective = LinearObjective(**plan["objective"])
    model = build(case, **plan["configuration"])
    method = variant["profile"]
    settings = dict(PROFILES.get(method, {}))
    settings.update(variant["overrides"])
    activity = []
    original = v2.policy.candidates if method == "simple" else improved.policy.candidates
    if "adaptive" in variant:
        spec = importlib.util.spec_from_file_location("sensitivity_adaptive", ADAPTIVE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = module.candidates

    def observe(*args, **kwargs):
        kwargs.update(variant.get("adaptive", {}))
        proposals, meta = original(*args, **kwargs)
        activity.append(
            {
                k: meta[k]
                for k in (
                    "proxy_evaluations",
                    "candidates",
                    "mutation_history",
                    "adaptive_mutation",
                    "adaptive_crossover",
                )
                if k in meta
            }
        )
        return proposals, meta

    # Both wall timeout (parent) and CPU hard limit (child) survive solver hangs.
    if os.name == "posix":
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU, (plan["limits"]["cpu_seconds"], plan["limits"]["cpu_seconds"] + 1)
        )
    cpu, wall = time.process_time(), time.perf_counter()
    with ExitStack() as stack:
        if method in PROFILES:
            stack.enter_context(patch.dict(PROFILES, {method: settings}))
        stack.enter_context(
            patch(
                "v2.policy.candidates" if method == "simple" else "improved.policy.candidates",
                observe,
            )
        )
        result = run(model, method, job["seed"], objective=objective)
        scoring = checked_score(model, result, objective)
    elapsed_cpu, elapsed_wall = time.process_time() - cpu, time.perf_counter() - wall
    valid = bool(result["valid"] and scoring["audit"]["valid"])
    row = dict(
        valid=valid,
        **{k: result[k] for k in METRICS},
        F=scoring["F_linear_v2"] if valid else None,
        cpu=elapsed_cpu,
        wall=elapsed_wall,
        tasks=len(case["tasks"]),
    )
    if valid and not math.isclose(
        row["F"], 0.5 * row["T"] / 900 + 0.3 * row["R"] / 900 + 0.2 * row["D"] / 5400, abs_tol=1e-12
    ):
        raise ValueError("Fitness does not match independently checked physical terms")
    trace = Path(plan["trace_root"]) / (trial_id + ".json.gz")
    trace.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        dict(
            job=job,
            variant=variant,
            case=case,
            result=result,
            scoring=scoring,
            row=row,
            settings=settings,
            operator_activity=activity,
        ),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    with trace.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
    check_sources(study)
    record = dict(
        **job,
        status="ok" if valid else "invalid",
        row=row,
        settings=settings,
        search=search_summary(result, settings, activity),
        independent_audit=scoring["audit"],
        case_sha256=digest(case),
        objective_sha256=objective.fingerprint,
        plan_sha256=sha(study / "plan.json"),
        sources=plan["sources"],
        trace=dict(path=str(trace), sha256=sha(trace), bytes=trace.stat().st_size),
    )
    write_new(study / "trials" / (trial_id + ".json"), record)
    print(json.dumps(dict(**job, status=record["status"], F=row["F"], cpu=elapsed_cpu)), flush=True)
    if not valid:
        raise SystemExit(1)


def run_study(study, workers=2):
    study = Path(study).resolve()
    plan = check_sources(study)
    if not 1 <= workers <= plan["limits"]["max_workers"]:
        raise ValueError("Worker count exceeds frozen resource limits")
    scheduled = {j["id"]: j for j in jobs(plan)}
    pending = []
    for trial_id in plan["execution_order"]:
        target = study / "trials" / (trial_id + ".json")
        if target.exists():
            trial = read(target)
            if trial.get("plan_sha256") != sha(study / "plan.json"):
                raise ValueError("Existing trial belongs to another plan")
        else:
            pending.append(scheduled[trial_id])
    environment = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    environment.pop("PYTHONPATH", None)

    def launch(job):
        logfile = Path(plan["trace_root"]).parent / "logs" / (job["id"] + ".log")
        logfile.parent.mkdir(parents=True, exist_ok=True)
        failure = None
        target = study / "trials" / (job["id"] + ".json")
        if logfile.exists():
            # A killed parent may leave a partial attempt. Keep it in the
            # denominator, never overwrite its log or silently retry it.
            write_new(
                target,
                dict(
                    **job,
                    status="interrupted",
                    row={"valid": False, "F": None},
                    log=str(logfile),
                    plan_sha256=sha(study / "plan.json"),
                    sources=plan["sources"],
                ),
            )
            return dict(id=job["id"], status="interrupted", F=None, cpu=None)
        with logfile.open("xb") as stream:
            try:
                process = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), "worker", str(study), job["id"]],
                    cwd=plan["runtime"],
                    env=environment,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=plan["limits"]["wall_seconds"],
                    check=False,
                )
                exitcode = process.returncode
                if exitcode:
                    failure = "cpu_timeout" if exitcode in (-24, -9) else "error"
            except subprocess.TimeoutExpired:
                failure, exitcode = "wall_timeout", 124
        if not target.exists():
            write_new(
                target,
                dict(
                    **job,
                    status=failure or "missing_output",
                    row={"valid": False, "F": None},
                    exitcode=exitcode,
                    log=str(logfile),
                    plan_sha256=sha(study / "plan.json"),
                    sources=plan["sources"],
                ),
            )
        trial = read(target)
        return dict(
            id=job["id"],
            status=trial["status"],
            F=trial["row"].get("F"),
            cpu=trial["row"].get("cpu"),
        )

    completed = len(scheduled) - len(pending)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(launch, job) for job in pending]
        for future in as_completed(futures):
            completed += 1
            print(
                json.dumps(dict(completed=completed, total=len(scheduled), **future.result())),
                flush=True,
            )
    verify(study, traces=True)


def verify(study, *, traces=False):
    study = Path(study).resolve()
    plan = check_sources(study)
    expected = {job["id"]: job for job in jobs(plan)}
    actual = {p.stem for p in (study / "trials").glob("*.json")}
    if actual != set(expected):
        raise ValueError(
            f"Trial set mismatch: missing={len(set(expected) - actual)}, extra={len(actual - set(expected))}"
        )
    failures = []
    for key, job in expected.items():
        trial = read(study / "trials" / (key + ".json"))
        if any(trial[k] != value for k, value in job.items()):
            raise ValueError("Trial identity mismatch: " + key)
        if trial["plan_sha256"] != sha(study / "plan.json"):
            raise ValueError("Trial plan mismatch: " + key)
        if trial["sources"] != plan["sources"]:
            raise ValueError("Trial source identity mismatch: " + key)
        if trial["status"] != "ok" or not trial["row"]["valid"]:
            failures.append(key)
            continue
        row = trial["row"]
        if any(
            not isinstance(row[k], (int, float)) or not math.isfinite(row[k]) or row[k] < 0
            for k in (*METRICS, "F", "cpu", "wall")
        ):
            raise ValueError("Invalid physical metrics: " + key)
        expected_f = 0.5 * row["T"] / 900 + 0.3 * row["R"] / 900 + 0.2 * row["D"] / 5400
        if not math.isclose(row["F"], expected_f, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Compact fitness differs from physical metrics: " + key)
        if trial["case_sha256"] != plan["case_provenance"][job["case"]]["sha256"]:
            raise ValueError("Trial scenario identity mismatch: " + key)
        if traces:
            if sha(trial["trace"]["path"]) != trial["trace"]["sha256"]:
                raise ValueError("Trajectory changed: " + key)
            with gzip.open(trial["trace"]["path"], "rt", encoding="utf-8") as stream:
                trace = json.load(stream)
            variant = next(v for v in plan["variants"] if v["id"] == job["variant"])
            if (
                trace["job"] != job
                or trace["variant"] != variant
                or trace["row"] != row
                or digest(trace["case"]) != trial["case_sha256"]
                or trace["scoring"]["objective_sha256"] != trial["objective_sha256"]
                or trace["scoring"]["F_linear_v2"] != row["F"]
                or not trace["scoring"]["audit"]["valid"]
                or any(trace["result"][k] != row[k] for k in METRICS)
                or search_summary(trace["result"], trace["settings"], trace["operator_activity"])
                != trial["search"]
            ):
                raise ValueError("Compact trial differs from audited trajectory: " + key)
    audit = dict(
        expected=len(expected),
        recorded=len(actual),
        valid=len(expected) - len(failures),
        failures=failures,
        all_valid=not failures,
        traces_checked=traces,
        plan_sha256=sha(study / "plan.json"),
    )
    print(json.dumps(audit), flush=True)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("study")
    init.add_argument("--runtime", required=True)
    run = commands.add_parser("run")
    run.add_argument("study")
    run.add_argument("--workers", type=int, default=2)
    child = commands.add_parser("worker")
    child.add_argument("study")
    child.add_argument("trial_id")
    check = commands.add_parser("verify")
    check.add_argument("study")
    check.add_argument("--traces", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.study, args.runtime)
    elif args.command == "run":
        run_study(args.study, args.workers)
    elif args.command == "worker":
        worker(args.study, args.trial_id)
    else:
        verify(args.study, traces=args.traces)


if __name__ == "__main__":
    main()
