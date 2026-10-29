#!/usr/bin/env python3
"""Serial measured-latency sensitivity runs; never a method-adoption protocol."""

import argparse
import copy
import hashlib
import json
import platform
from pathlib import Path

from agv.experiments.cache import cache_key
from agv.experiments.wepa import _trial, freeze_protocol, load_protocol
from agv.io.storage import write_json

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
METHODS = ["gate", "gate_anchor", "hungarian"]
LATENCY = dict(kind="measured", scale=1)


def configuration(base):
    config = copy.deepcopy(base["config"])
    config.update(methods=METHODS[:], baseline="gate", latency=LATENCY.copy(), timeout_seconds=360)
    config.pop("validation_controls", None)
    return config


def ignored(path):
    path = Path(path).resolve()
    if not path.is_relative_to(RUNS.resolve()):
        raise ValueError("Full protocols and traces must stay under the repository runs directory")
    return path


def measurement_plan(base, frozen):
    return dict(
        schema="agv-wepa-measured-latency-plan-v1",
        base_protocol_sha256=base["protocol_sha256"],
        supplemental_protocol_sha256=frozen["protocol_sha256"],
        sources_sha256=cache_key(base["sources"]),
        objective_id=frozen["objective_id"],
        case_ids=base["config"]["validation"],
        methods=METHODS,
        seeds=base["config"]["seeds"],
        latency=LATENCY,
        timeout_seconds=360,
        serial_workers=1,
        cache=False,
        nondeterministic=True,
        not_for_adoption=True,
        environment=dict(
            python=platform.python_version(),
            platform=platform.platform(),
            machine=platform.machine(),
        ),
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def prepare(base_path, protocol_path, plan_path):
    protocol_path, plan_path = ignored(protocol_path), Path(plan_path)
    if protocol_path.exists() or plan_path.exists():
        raise FileExistsError("Refuse to replace a prepared protocol or measurement plan")
    base = load_protocol(base_path)
    frozen = freeze_protocol(configuration(base), protocol_path)
    if frozen["sources"] != base["sources"]:
        raise ValueError("Source changed while preparing the sensitivity protocol")
    plan = measurement_plan(base, frozen)
    write_json(plan_path, plan)
    return plan


def run(base_path, protocol_path, plan_path, output):
    protocol_path, output = ignored(protocol_path), ignored(output)
    base, frozen = load_protocol(base_path), load_protocol(protocol_path)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if (
        frozen["config"] != configuration(base)
        or frozen["sources"] != base["sources"]
        or plan != measurement_plan(base, frozen)
    ):
        raise ValueError("Measurement plan, environment or frozen configuration differs")
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(
        schema="agv-wepa-measured-latency-results-v1",
        plan_sha256=cache_key(plan),
        not_for_adoption=True,
        nondeterministic=True,
        status="running",
        rows=[],
    )
    target = output / "summary.json"
    write_json(target, summary)
    try:
        for case in base["config"]["validation"]:
            for method in METHODS:
                for seed in base["config"]["seeds"]:
                    raw = output / f"{case}--{method}--s{seed}.json"
                    row = _trial((str(protocol_path), case, method, seed, str(raw), None))
                    if row["status"] == "complete":
                        trace = json.loads(raw.read_text(encoding="utf-8"))
                        row["independent_audit"] = trace["scoring"]["audit"]
                    summary["rows"].append(row)
                    write_json(target, summary, overwrite=True)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
        load_protocol(base_path)
        load_protocol(protocol_path)
    except Exception as error:
        summary.update(status="aborted", error=f"{type(error).__name__}: {error}")
        write_json(target, summary, overwrite=True)
        raise
    summary.update(
        status="complete", failed=sum(row["status"] != "complete" for row in summary["rows"])
    )
    write_json(target, summary, overwrite=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = sub.add_parser(name)
        command.add_argument(
            "--base", type=Path, default=ROOT / "protocols/wepa-20261029-dates.json"
        )
        command.add_argument("--protocol", type=Path, required=True)
        command.add_argument("--plan", type=Path, required=True)
        if name == "run":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(
            json.dumps(prepare(args.base, args.protocol, args.plan), ensure_ascii=False, indent=2)
        )
    else:
        run(args.base, args.protocol, args.plan, args.output)


if __name__ == "__main__":
    main()
