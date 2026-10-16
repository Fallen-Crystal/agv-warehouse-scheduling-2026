#!/usr/bin/env python3
"""Audit a completed BCRD result directory without re-running its policies.

Checks matrix completeness, artifact hashes, frozen protocol, independent paired
arithmetic, summary reproducibility, and independent validation of every retained
trace. --revision checks measured source against a committed Git snapshot;
omitting it requires the current source tree to match exactly.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
from pathlib import Path

from agv.evaluation.validation import validate
from agv.experiments.bcrd import protocol_id, read_rows, summarize, validate_protocol
from agv.experiments.benchmark import source_hashes
from agv.io.scenes import unpack_scene

ROOT = Path(__file__).resolve().parents[1]


def _close(a, b):
    if isinstance(b, dict):
        return (
            isinstance(a, dict)
            and a.keys() == b.keys()
            and all(_close(a[k], v) for k, v in b.items())
        )
    if isinstance(b, list):
        return isinstance(a, list) and len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if type(b) is float:
        return type(a) in (int, float) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return a == b


def _independent_summary(rows, saved, protocol):
    baseline = protocol.get("baseline", "G0")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    boot = protocol.get("bootstrap", {"resamples": 4000, "seed": 20261016})
    for group in saved["groups"]:
        own = [
            r
            for r in rows
            if r["solver"] == group["solver"]
            and (group["scenario"] == "__all__" or r["scenario"] == group["scenario"])
        ]
        pairs = [(index[r["scenario"], r["seed"], baseline], r) for r in own]
        pairs = [(a, b) for a, b in pairs if a["comparison_valid"] and b["comparison_valid"]]
        effects = [
            100 * (a["weighted_score"] - b["weighted_score"]) / a["weighted_score"]
            for a, b in pairs
            if a["weighted_score"] > 0
        ]
        expected = statistics.mean(effects) if effects else None
        if not _close(group["paired_F_improvement_pct_mean"], expected):
            raise ValueError("Independent paired improvement calculation differs")
        wins = sum(b["weighted_score"] < a["weighted_score"] - 1e-12 for a, b in pairs)
        losses = sum(b["weighted_score"] > a["weighted_score"] + 1e-12 for a, b in pairs)
        if (group["score_wins"], group["score_losses"], group["score_ties"]) != (
            wins,
            losses,
            len(pairs) - wins - losses,
        ):
            raise ValueError("Independent win/loss/tie calculation differs")
        if group["excluded_pairs"] != len(own) - len(pairs):
            raise ValueError("Failure/missing-pair accounting differs")
        if effects:
            rng = random.Random(boot["seed"])
            samples = sorted(
                sum(effects[rng.randrange(len(effects))] for _ in effects) / len(effects)
                for _ in range(boot["resamples"])
            )
            ci = [
                samples[math.floor(0.025 * (boot["resamples"] - 1))],
                samples[math.ceil(0.975 * (boot["resamples"] - 1))],
            ]
            if not _close(group["paired_F_improvement_pct_95ci"], ci):
                raise ValueError("Independent bootstrap interval differs")
        if group["p90_degradations"] != sum(
            b["p90_flow_time"] > a["p90_flow_time"] for a, b in pairs
        ):
            raise ValueError("P90 degradation count differs")


def verify(directory, revision=None):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "agv-bcrd-results-v1" or manifest.get("status") != "complete":
        raise ValueError("BCRD experiment is not complete/frozen")
    protocol_raw = (root / "protocol.json").read_bytes()
    protocol = json.loads(protocol_raw.decode("utf-8-sig"))
    validate_protocol(protocol, require_frozen=protocol["split"] != "development")
    if (
        protocol_id(protocol) != manifest["protocol_sha256"]
        or hashlib.sha256(protocol_raw).hexdigest() != manifest["protocol_file_sha256"]
    ):
        raise ValueError("Protocol hash mismatch")
    for name, digest in manifest["artifact_hashes"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Artifact path escapes result directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Changed artifact: {name}")
    if revision is None:
        actual = source_hashes()
        if actual != manifest["source_hashes"]:
            raise ValueError(
                "Current source differs; use --revision for the measured committed snapshot"
            )
    else:
        files = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", revision, "src/agv"], cwd=ROOT, text=True
        ).splitlines()
        actual = {}
        for filename in files:
            if Path(filename).suffix in (".py", ".json", ".js", ".html", ".css"):
                raw = subprocess.check_output(["git", "show", f"{revision}:{filename}"], cwd=ROOT)
                actual[str(Path(filename).relative_to("src/agv"))] = hashlib.sha256(raw).hexdigest()
        if actual != manifest["source_hashes"]:
            raise ValueError("Git snapshot differs from measured source hashes")
    rows = read_rows(root / "runs.csv")
    expected = {
        (name, seed, solver)
        for name in protocol["configs"]
        for seed in protocol["seeds"]
        for solver in protocol["solvers"]
    }
    actual = [(r["scenario"], r["seed"], r["solver"]) for r in rows]
    if (
        len(actual) != len(expected)
        or set(actual) != expected
        or len(rows) != manifest["expected_runs"]
    ):
        raise ValueError("Incomplete or duplicated experiment matrix")
    for row in rows:
        if row["comparison_valid"] and (
            not row["execution_valid"] or not row["feasible"] or row["weighted_score"] is None
        ):
            raise ValueError("Invalid run counted as comparable")
        if not row["comparison_valid"] and any(
            row[key] is not None
            for key in ("weighted_score", "makespan", "mean_flow_time", "moves")
        ):
            raise ValueError("Failed run exposes misleading comparable full-task costs")
    saved = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    if not _close(saved, summarize(rows, protocol)):
        raise ValueError("Saved summary differs from complete CSV reconstruction")
    _independent_summary(rows, saved, protocol)
    diagnostics = [
        json.loads(line)
        for line in (root / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if (
        len(diagnostics) != len(rows)
        or {(r["scenario"], r["seed"], r["solver"]) for r in diagnostics} != expected
    ):
        raise ValueError("Missing per-run diagnostic evidence")
    index = {(r["scenario"], r["seed"], r["solver"]): r for r in rows}
    validated, retained_failures = 0, 0
    for path in sorted((root / "traces").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scene = unpack_scene(data)
        config = data["config"]
        row = index.get((config["scenario"], config["seed"], config["solver"]))
        if row is None or row["scenario_sha256"] != data["scenario_sha256"]:
            raise ValueError("Trace does not match its matrix row")
        if data["experiment_audit"]["execution_valid"]:
            validate(scene, data["result"])
            validated += 1
            if row["comparison_valid"]:
                for key in (
                    "weighted_score",
                    "makespan",
                    "mean_flow_time",
                    "p90_flow_time",
                    "max_flow_time",
                    "moves",
                ):
                    if not _close(data["result"][key], row[key]):
                        raise ValueError("Trace metrics differ from CSV")
        elif data["experiment_audit"].get("error") and not row["execution_valid"]:
            retained_failures += 1
        else:
            raise ValueError("Invalid trace audit state")
    if validated + retained_failures != manifest["representative_traces"]:
        raise ValueError("Missing representative traces")
    return dict(
        status="verified",
        rows=len(rows),
        independent_traces_validated=validated,
        retained_failed_traces=retained_failures,
        source_revision=revision or "current",
        protocol_sha256=manifest["protocol_sha256"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--revision")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.revision), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
