"""Seal and verify portable trajectory evidence, without rerunning physical validation."""

import argparse
import gzip
import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path

METRICS = ("T", "R", "D", "p90", "empty_distance", "traffic_wait")
SCHEMA = "agv-sensitivity-evidence-v1"
COUNT = 200


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value, *, compact=False):
    options = {"separators": (",", ":")} if compact else {}
    return sha(json.dumps(value, sort_keys=True, **options).encode())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def _study(study):
    study = Path(study).resolve()
    plan, freeze = read(study / "plan.json"), read(study / "freeze.json")
    require(
        sha((study / "plan.json").read_bytes()) == freeze["plan_sha256"], "Frozen plan mismatch"
    )
    require(freeze["sources"] == plan["sources"], "Frozen source identities mismatch")
    variants = {v["id"]: v for v in plan["variants"]}
    require(len(variants) == len(plan["variants"]), "Duplicate variant")
    jobs = []
    for variant in plan["variants"]:
        for case in plan["cases"]:
            for seed in variant.get("seeds", plan["seeds"]):
                name = f"{case}__{variant['id']}__s{seed}"
                require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) is not None, "Unsafe trial identity")
                jobs.append(dict(id=name, case=case, variant=variant["id"], seed=seed))
    require(plan["expected_trials"] == COUNT and len(jobs) == COUNT, "Expected exactly 200 trials")
    require(len({job["id"] for job in jobs}) == COUNT, "Duplicate planned trial")
    require(
        len(plan["execution_order"]) == COUNT
        and set(plan["execution_order"]) == {job["id"] for job in jobs},
        "Execution order mismatch",
    )
    paths = {p.name: p for p in (study / "trials").glob("*.json")}
    require(set(paths) == {job["id"] + ".json" for job in jobs}, "Trial set mismatch")
    files = {
        "plan.json": sha((study / "plan.json").read_bytes()),
        "freeze.json": sha((study / "freeze.json").read_bytes()),
    }
    trials = {}
    for job in jobs:
        path = paths[job["id"] + ".json"]
        require(path.resolve().is_relative_to(study), "Trial escapes study directory")
        raw = path.read_bytes()
        trial = json.loads(raw)
        require(all(trial[k] == value for k, value in job.items()), "Trial identity mismatch")
        require(
            trial["plan_sha256"] == files["plan.json"] and trial["sources"] == plan["sources"],
            "Trial source or plan mismatch",
        )
        row = trial["row"]
        require(trial["status"] == "ok" and row["valid"] is True, "Incomplete or invalid trial")
        require(
            all(
                isinstance(row[k], (int, float))
                and not isinstance(row[k], bool)
                and math.isfinite(row[k])
                and row[k] >= 0
                for k in (*METRICS, "F", "cpu", "wall")
            ),
            "Invalid physical metrics",
        )
        require(
            math.isclose(
                row["F"],
                0.5 * row["T"] / 900 + 0.3 * row["R"] / 900 + 0.2 * row["D"] / 5400,
                rel_tol=0,
                abs_tol=1e-12,
            ),
            "Fitness mismatch",
        )
        require(
            trial["case_sha256"] == plan["case_provenance"][job["case"]]["sha256"],
            "Scenario identity mismatch",
        )
        files["trials/" + path.name] = sha(raw)
        trials[job["id"]] = trial
    return study, plan, variants, jobs, trials, files


def _trace(plan, variants, job, trial, raw):
    require(
        sha(raw) == trial["trace"]["sha256"] and len(raw) == trial["trace"]["bytes"],
        "Trajectory digest or length mismatch",
    )
    trace = json.loads(gzip.decompress(raw))
    result, scoring, settings = trace["result"], trace["scoring"], trace["settings"]
    row, variant = trial["row"], variants[job["variant"]]
    objective_hash = digest(plan["objective"], compact=True)
    require(
        trace["job"] == job and trace["variant"] == variant, "Trajectory job or variant mismatch"
    )
    require(
        trace["case"]["case"] == job["case"] and digest(trace["case"]) == trial["case_sha256"],
        "Trajectory case mismatch",
    )
    require(
        row["tasks"]
        == len(trace["case"]["tasks"])
        == plan["case_provenance"][job["case"]]["tasks"],
        "Task count mismatch",
    )
    require(
        trace["row"] == row
        and settings == trial["settings"]
        and all(settings[k] == value for k, value in variant["overrides"].items()),
        "Trajectory row or settings mismatch",
    )
    require(
        result["valid"] is True and all(result[k] == row[k] for k in METRICS),
        "Trajectory physical metrics mismatch",
    )
    require(
        result["method"] == variant["profile"] and result["objective"] == plan["objective"],
        "Trajectory model or objective mismatch",
    )
    require(
        trial["objective_sha256"]
        == scoring["objective_sha256"]
        == result["objective_sha256"]
        == objective_hash,
        "Objective identity mismatch",
    )
    require(
        scoring["F_linear_v2"] == row["F"]
        and math.isclose(scoring["J_equivalent_seconds"], 900 * row["F"], rel_tol=0, abs_tol=1e-10)
        and scoring["audit"]["valid"] is True
        and scoring["audit"] == trial["independent_audit"],
        "Recorded scoring or audit mismatch",
    )
    terms = {
        k: w * row[k] / scale
        for k, w, scale in zip(("T", "R", "D"), (0.5, 0.3, 0.2), (900, 900, 5400))
    }
    require(
        all(
            math.isclose(scoring["weighted_terms"][k], value, rel_tol=0, abs_tol=1e-12)
            for k, value in terms.items()
        ),
        "Recorded objective terms mismatch",
    )
    searches = [r for r in result["search_log"] if "proxy_evaluations" in r]
    search = dict(
        searches=len(searches),
        proxy_evaluations=sum(r["proxy_evaluations"] for r in searches),
        previews=sum(r["previews"] for r in searches),
        gate_decisions=sum(
            r.get("mode") == "immediate_batch_matching" for r in result["search_log"]
        ),
        proxy_cap_hits=sum(r["proxy_evaluations"] >= settings.get("proxy", 96) for r in searches),
        preview_cap_hits=sum(r["previews"] >= settings.get("previews", 3) for r in searches),
        improvements=sum(bool(r.get("changed")) for r in searches),
        operator_activity=trace["operator_activity"],
    )
    require(search == trial["search"], "Recorded search activity mismatch")


def seal(study):
    study = Path(study).resolve()
    for name in ("trajectories.zip", "evidence.json"):
        if (study / name).exists():
            raise FileExistsError(study / name)
    study, plan, variants, jobs, trials, files = _study(study)
    buffer, members = io.BytesIO(), {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for job in sorted(jobs, key=lambda j: j["id"]):
            trial = trials[job["id"]]
            raw = Path(trial["trace"]["path"]).read_bytes()
            _trace(plan, variants, job, trial, raw)
            name = job["id"] + ".json.gz"
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system, info.external_attr = 3, 0o100644 << 16
            archive.writestr(info, raw)
            members[name] = dict(sha256=sha(raw), bytes=len(raw))
    require(
        all(sha((study / name).read_bytes()) == expected for name, expected in files.items()),
        "Study changed during sealing",
    )
    payload = buffer.getvalue()
    files["trajectories.zip"] = sha(payload)
    evidence = dict(
        schema=SCHEMA,
        study_id=plan["study_id"],
        expected_trials=COUNT,
        scope="Archive and recorded-audit consistency; no new physical validation",
        files=files,
        members=members,
    )
    with (study / "trajectories.zip").open("xb") as stream:
        stream.write(payload)
    with (study / "evidence.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return verify(study)


def verify(study):
    study, plan, variants, jobs, trials, files = _study(study)
    evidence = read(study / "evidence.json")
    require(
        evidence["schema"] == SCHEMA
        and evidence["study_id"] == plan["study_id"]
        and evidence["expected_trials"] == COUNT,
        "Evidence identity mismatch",
    )
    payload = (study / "trajectories.zip").read_bytes()
    files["trajectories.zip"] = sha(payload)
    require(evidence["files"] == files, "Evidence file digest mismatch")
    expected = {job["id"] + ".json.gz" for job in jobs}
    require(set(evidence["members"]) == expected, "Evidence member set mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        require(
            len(names) == len(set(names)) and set(names) == expected,
            "Unsafe, duplicate or missing archive member",
        )
        for job in jobs:
            name = job["id"] + ".json.gz"
            raw = archive.read(name)
            require(
                evidence["members"][name] == dict(sha256=sha(raw), bytes=len(raw)),
                "Archived trajectory digest mismatch",
            )
            _trace(plan, variants, job, trials[job["id"]], raw)
    return dict(
        study_id=plan["study_id"],
        expected=COUNT,
        recorded=len(trials),
        valid=COUNT,
        all_checks=True,
        physical_validation_rerun=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seal", "verify"))
    parser.add_argument("study", type=Path)
    args = parser.parse_args()
    print(json.dumps((seal if args.command == "seal" else verify)(args.study), ensure_ascii=False))


if __name__ == "__main__":
    main()
