"""Audit frozen sources/results and export readable full-precision comparisons."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from zipfile import ZipFile

from agv.experiments.search_benchmark import fingerprints

ROOT = Path("results/path-study-20261022")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()]


def zip_frame(path):
    with ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError("Corrupt source snapshot")
        return {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}


def write_csv(path, data):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)


def main():
    current = fingerprints()
    joint = zip_frame("results/joint-study-20261022/source-snapshot.zip")
    development = zip_frame(ROOT / "development-source.zip")
    base = zip_frame(ROOT / "baseline-source.zip")
    changed = [p for p, h in base.items() if current.get(p) != h]
    if sorted(changed) != ["src/agv/runner/environment.py", "src/agv/runner/run.py"]:
        raise ValueError(f"Unexpected change to existing model files: {changed}")
    phase_specs = [
        (Path("results/joint-study-20261022/pilot"), 14, joint),
        (Path("results/joint-study-20261022/development"), 84, joint),
        *[
            (ROOT / n, c, development)
            for n, c in (("development", 180), ("tiny", 144), ("stress", 12))
        ],
        *[
            (ROOT / n, c, current)
            for n, c in (
                ("confirmation", 120),
                ("path-ablation", 24),
                ("robustness", 80),
                ("robust-path-ablation", 16),
                ("matched-arrivals", 48),
                ("release-tiny", 8),
                ("release-stress", 2),
                ("recommendation-stress", 2),
                ("interface-replay", 12),
            )
        ],
    ]
    phases, numeric_checks = [], 0
    for directory, count, frame in phase_specs:
        summary = read(directory / "summary.json")
        valid = summary.get("valid", count if summary.get("all_equal") else 0)
        if summary["runs"] != count or valid != count:
            raise ValueError(f"Incomplete phase {directory}")
        freeze = (
            read(directory / "freeze.json") if (directory / "freeze.json").exists() else summary
        )
        if freeze["source_sha256"] != frame:
            raise ValueError(f"Incorrect source version {directory}")
        if (directory / "rows.jsonl").exists():
            for r in rows(directory / "rows.jsonl"):
                if all(k in r for k in ("nt", "nr", "nd", "F")):
                    if abs(0.5 * r["nt"] + 0.3 * r["nr"] + 0.2 * r["nd"] - r["F"]) > 1e-10:
                        raise ValueError("Official F reconstruction mismatch")
                    numeric_checks += 1
        phases.append(dict(directory=str(directory), runs=count, valid=valid, source_verified=True))
    for name in ("pilot", "pilot-fixed"):
        frame = zip_frame(ROOT / name / "source-snapshot.zip")
        if read(ROOT / name / "freeze.json")["source_sha256"] != frame:
            raise ValueError("Prototype source snapshot mismatch")
    tiny = read(ROOT / "tiny/summary.json")
    fresh = read(ROOT / "release-tiny/summary.json")
    if not all(r["certified_optimal"] for d in (tiny, fresh) for r in d["rows"]):
        raise ValueError("A claimed tiny optimum was not attained")
    common = {}
    for r in rows("results/joint-study-20261022/development/rows.jsonl"):
        if r["variant"] in ("portfolio", "assignment"):
            common[r["map"], r["mode"], r["seed"], r["variant"]] = r
    repeated = 0
    for r in rows(ROOT / "development/rows.jsonl"):
        method = r["variant"].removesuffix("__sipp")
        key = r["map"], r["mode"], r["seed"], method
        if key in common:
            if any(abs(r[k] - common[key][k]) > 1e-10 for k in ("F", "T", "R", "D")):
                raise ValueError("Shared development baseline changed")
            repeated += 1
    if repeated != 24:
        raise ValueError("Missing shared development controls")
    main_report = read(ROOT / "confirmation/profile-report.json")
    ablation = read(ROOT / "confirmation-combined/ablation-report.json")
    comparison = ablation["comparisons"]["simplified_profile_vs_portfolio"]
    all_rows = rows(ROOT / "confirmation-combined/rows.jsonl")
    index = {(r["map"], r["mode"], r["seed"], r["variant"]): r for r in all_rows}
    cases = sorted({key[:3] for key in index})
    table, auxiliary, bounds = [], defaultdict(list), []
    lower = {r["case"]: r["lower_F"] for r in main_report["offline_bound_diagnostics"]["cases"]}
    feedback = dict(accepted=0, rejected_batches=0, prediction_mismatch_batches=0)
    for size, mode, seed in cases:
        method = "assignment__sipp" if mode == "static" else "aco__sipp"
        old, new = index[size, mode, seed, "portfolio__sipp"], index[size, mode, seed, method]
        case = f"{size}-{mode}-{seed}"
        table.append(
            dict(
                map=size,
                mode=mode,
                seed=seed,
                method=method,
                baseline_F=old["F"],
                F=new["F"],
                gain_pct=100 * (1 - new["F"] / old["F"]),
                T=new["T"],
                R=new["R"],
                D=new["D"],
                E=0.05 * new["D"],
            )
        )
        bound = lower[case]
        if new["F"] < bound - 1e-10:
            raise ValueError("Execution below proven bound")
        bounds.append(
            dict(
                case=case,
                F=new["F"],
                lower_F=bound,
                conservative_gap_upper_pct=100 * (new["F"] / bound - 1),
            )
        )
        for label, variant in (("baseline", "portfolio__sipp"), ("candidate", method)):
            directory = "path-ablation" if variant == "aco__sipp" else "confirmation"
            result = read(ROOT / directory / "traces" / f"{case}-{variant}-0.json")
            for key in (
                "empty_moves",
                "loaded_moves",
                "traffic_wait_steps",
                "mean_dispatch_wait",
                "workload_cv",
            ):
                auxiliary[label + "/" + key].append(result[key])
            if label == "candidate":
                for f in result["path_research"]["commit_feedback"]:
                    feedback["accepted"] += f["accepted"]
                    feedback["rejected_batches"] += f["rejected"]
                    feedback["prediction_mismatch_batches"] += f["prediction_mismatch"]
    if abs(mean(r["gain_pct"] for r in table) - comparison["mean_gain_pct"]) > 1e-10:
        raise ValueError("Scene summary differs from primary comparison")
    write_csv(ROOT / "逐场景确认结果.csv", table)
    summary_table = []
    specifications = [
        ("上一轮Portfolio+SIPP", comparison["baseline_means"], 0, 1),
        (
            "统一邻域调度+SIPP",
            main_report["comparisons"]["assignment_vs_portfolio"]["means"],
            main_report["comparisons"]["assignment_vs_portfolio"]["overall"]["mean_gain_pct"],
            main_report["comparisons"]["assignment_vs_portfolio"]["overall"]["mean_cpu_ratio"],
        ),
        (
            "分场景调度+SIPP",
            comparison["means"],
            comparison["mean_gain_pct"],
            comparison["mean_cpu_ratio"],
        ),
        (
            "分场景调度+蚁群路径",
            main_report["comparisons"]["profile_vs_portfolio"]["means"],
            main_report["comparisons"]["profile_vs_portfolio"]["overall"]["mean_gain_pct"],
            main_report["comparisons"]["profile_vs_portfolio"]["overall"]["mean_cpu_ratio"],
        ),
    ]
    for name, metrics, gain, cpu in specifications:
        summary_table.append(
            dict(
                方案=name,
                平均F=metrics["F"],
                平均T=metrics["T"],
                平均R=metrics["R"],
                平均D=metrics["D"],
                估算E=0.05 * metrics["D"],
                平均场景P90=metrics["p90"],
                配对F下降百分比=gain,
                配对CPU倍数=cpu,
            )
        )
    write_csv(ROOT / "方案汇总.csv", summary_table)
    matching = []
    for path in sorted((ROOT / "matched-arrivals/scenes").glob("*-dynamic-*.json")):
        dynamic = read(path)
        static = read(path.with_name(path.name.replace("-dynamic-", "-static-")))
        dynamic["order_stream_end"] = static["order_stream_end"]
        for j in dynamic["tasks"]:
            j["release"] = 0
        if dynamic != static:
            raise ValueError("Matched arrival panel changed more than timing")
        matching.append(path.stem)
    negative = []
    for r in rows(ROOT / "robustness-combined/rows.jsonl"):
        if (r["map"], r["mode"], r["seed"]) == ("large", "dynamic", 19100) and r["variant"] in (
            "assignment__sipp",
            "aco__sipp",
        ):
            negative.append({k: r[k] for k in ("variant", "optimizer_seed", "F", "T", "R", "D")})
    (ROOT / "负例_大型动态19100.json").write_text(json.dumps(negative, indent=2), encoding="utf-8")
    evidence = dict(
        source_files=len(current),
        base_source_files=len(base),
        changed_existing=changed,
        added_sources=sorted(set(current) - set(base)),
        phases=phases,
        archived_complete_runs=sum(x["runs"] for x in phases),
        official_score_reconstructions=numeric_checks,
        shared_control_pairs_equal=repeated,
        matched_arrival_pairs=len(matching),
        tiny_certified_runs=tiny["runs"],
        distinct_tiny_cases=8,
        fresh_tiny_certified_runs=fresh["runs"],
        feedback=feedback,
        auxiliary_means={k: mean(v) for k, v in auxiliary.items()},
        candidate_bound_upper_mean_pct=mean(x["conservative_gap_upper_pct"] for x in bounds),
        bound_note="Conservative upper bound from relaxed lower bounds, not measured distance to true optimum",
        prototype_failures=30,
        interrupted_valid_traces=read(ROOT / "pilot-fixed/interruption.json")["completed_traces"],
        all_checks_passed=True,
    )
    (ROOT / "candidate-bounds.json").write_text(json.dumps(bounds, indent=2), encoding="utf-8")
    (ROOT / "交付核验.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in evidence.items()
                if k not in ("phases", "added_sources", "auxiliary_means")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
