#!/usr/bin/env python3
"""Held-out WEPA validation-split multi-seed & hyperparameter sensitivity study.

Complements results/sensitivity-20261120-v2 (which evaluated the 4 development
windows only) by evaluating the 4 held-out validation windows, an upper
generations bound (gate_gen24), and the combined hga + adaptive_crossover variant.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import math
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADAPTIVE = ROOT / "research/dqn-experiment-v2/adaptive_genetic.py"
DEFAULT_RUNTIME = ROOT / "runs/validation-runtime"
DEFAULT_OUT = ROOT / "results/sensitivity-20261121-validation"


def _variants() -> list[dict]:
    items = [
        dict(id=name, profile=name, overrides={}, group="evolution", seeds=[0, 1])
        for name in ("fcfs", "eta", "hungarian")
    ]
    items += [
        dict(id=name, profile=name, overrides={}, group="evolution", seeds=[0, 1, 2])
        for name in ("simple", "wide", "gate", "hga")
    ]
    for name, overrides in (
        ("gate_preview3", dict(previews=3)),
        ("gate_gen8", dict(generations=8)),
        ("gate_gen24", dict(generations=24)),
    ):
        items.append(
            dict(id=name, profile="gate", overrides=overrides, group="budget", seeds=[0, 1, 2])
        )
    for mutation, crossover in ((False, False), (False, True), (True, True)):
        items.append(
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
    items.append(
        dict(
            id="hga_adapt01",
            profile="hga",
            overrides={},
            group="combined",
            seeds=[0, 1, 2],
            adaptive=dict(
                adaptive_mutation=False,
                adaptive_crossover=True,
                mutation_rate=0.7,
                crossover_rate=0.9,
            ),
        )
    )
    return items


def _worker(job: dict) -> dict:
    runtime = Path(job["runtime"]).resolve()
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    importlib.import_module("paths")
    import improved.policy
    import v2.policy
    from improved.execute import run
    from improved.profiles import PROFILES
    from objective import LinearObjective, checked_score
    from wepa.data import build

    proto = json.loads((runtime / "data/protocol.json").read_text(encoding="utf-8"))
    case = next(c for c in proto["cases"] if c["case"] == job["case"])
    objective = LinearObjective(**proto["objective"])
    model = build(case, **proto["configuration"])
    variant = job["variant_spec"]
    method = variant["profile"]
    settings = dict(PROFILES.get(method, {}))
    settings.update(variant["overrides"])

    original = v2.policy.candidates if method == "simple" else improved.policy.candidates
    if "adaptive" in variant:
        spec = importlib.util.spec_from_file_location("validation_adaptive", ADAPTIVE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = module.candidates

    def observe(*args, **kwargs):
        kwargs.update(variant.get("adaptive", {}))
        return original(*args, **kwargs)

    t0 = time.perf_counter()
    cpu0 = time.process_time()
    with ExitStack() as stack:
        if method in PROFILES:
            stack.enter_context(patch.dict(PROFILES, {method: settings}))
        if "adaptive" in variant:
            stack.enter_context(patch.object(improved.policy, "candidates", observe))
        result = run(model, method=method, seed=job["seed"], objective=objective)
    cpu = time.process_time() - cpu0
    wall = time.perf_counter() - t0
    scored = checked_score(model, result, objective)
    valid = bool(scored["audit"]["valid"] and result.get("valid", True))
    return dict(
        id=job["id"],
        case=job["case"],
        source_day=case["source_day"],
        group=variant["group"],
        variant=variant["id"],
        seed=job["seed"],
        valid=valid,
        F=float(scored["F_linear_v2"]),
        T=float(result["T"]),
        R=float(result["R"]),
        D=float(result["D"]),
        p90=float(result["p90"]),
        empty_distance=float(result["empty_distance"]),
        traffic_wait=float(result["traffic_wait"]),
        cpu=round(cpu, 6),
        wall=round(wall, 6),
    )


def _date_equal_mean(rows: list[dict], key: str) -> float:
    by_day_case: dict[tuple[int, str], list[float]] = {}
    for row in rows:
        by_day_case.setdefault((row["source_day"], row["case"]), []).append(row[key])
    by_day: dict[int, list[float]] = {}
    for (day, _), vals in by_day_case.items():
        by_day.setdefault(day, []).append(statistics.mean(vals))
    return statistics.mean(statistics.mean(vals) for vals in by_day.values())


def _seed_sd_mean(rows: list[dict]) -> float:
    by_case: dict[str, list[float]] = {}
    for row in rows:
        by_case.setdefault(row["case"], []).append(row["F"])
    sds = [statistics.stdev(vals) if len(vals) > 1 else 0.0 for vals in by_case.values()]
    return statistics.mean(sds)


def _paired_pct(rows: list[dict], cand: str, ref: str) -> tuple[float, int, int, int]:
    idx = {(r["case"], r["variant"], r["seed"]): r for r in rows}
    days: dict[int, list[float]] = {}
    for (case, variant, seed), c_row in idx.items():
        if variant != cand:
            continue
        r_row = idx.get((case, ref, seed))
        if r_row is None:
            continue
        pct = 100.0 * (1.0 - c_row["F"] / r_row["F"])
        days.setdefault(c_row["source_day"], []).append(pct)
    day_means = [statistics.mean(v) for v in days.values()]
    wins = sum(x > 1e-9 for x in day_means)
    ties = sum(abs(x) <= 1e-9 for x in day_means)
    losses = sum(x < -1e-9 for x in day_means)
    return statistics.mean(day_means), wins, ties, losses


def _svg_bars(
    title: str, subtitle: str, items: list[tuple[str, float, float, str]], y_label: str
) -> str:
    w, h = 840, 360
    ml, mr, mt, mb = 78, 25, 65, 95
    pw, ph = w - ml - mr, h - mt - mb
    vals = [v for _, v, _, _ in items]
    lo = min(vals) * 0.96
    hi = max(v + sd for _, v, sd, _ in items) * 1.03
    span = hi - lo if hi > lo else 0.05

    def y_px(val: float) -> float:
        return mt + ph - ((val - lo) / span) * ph

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{ml}" y="26" font-family="sans-serif" font-size="16" font-weight="bold" fill="#1e293b">{title}</text>',
        f'<text x="{ml}" y="46" font-family="sans-serif" font-size="12" fill="#64748b">{subtitle}</text>',
        f'<text x="18" y="{mt + ph / 2:.1f}" font-family="sans-serif" font-size="12" fill="#334155" transform="rotate(-90 18 {mt + ph / 2:.1f})" text-anchor="middle">{y_label}</text>',
    ]
    for step in range(5):
        val = lo + span * step / 4
        yp = y_px(val)
        out.append(
            f'<line x1="{ml}" y1="{yp:.1f}" x2="{w - mr}" y2="{yp:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{ml - 8}" y="{yp + 4:.1f}" font-family="sans-serif" font-size="11" fill="#475569" text-anchor="end">{val:.3f}</text>'
        )
    out.append(
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="#334155" stroke-width="1.2"/>'
    )
    out.append(
        f'<line x1="{ml}" y1="{mt + ph}" x2="{w - mr}" y2="{mt + ph}" stroke="#334155" stroke-width="1.2"/>'
    )

    slot = pw / max(1, len(items))
    bar_w = min(46.0, slot * 0.58)
    for i, (label, val, sd, color) in enumerate(items):
        cx = ml + slot * (i + 0.5)
        x0 = cx - bar_w / 2
        y0 = y_px(val)
        bh = max(1.0, (mt + ph) - y0)
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{color}"/>'
        )
        if sd > 0 and not math.isnan(sd):
            yt, ybot = y_px(min(hi, val + sd)), y_px(max(lo, val - sd))
            out.append(
                f'<line x1="{cx:.1f}" y1="{yt:.1f}" x2="{cx:.1f}" y2="{ybot:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
        out.append(
            f'<text x="{cx:.1f}" y="{y0 - 6:.1f}" font-family="sans-serif" font-size="10.5" font-weight="bold" fill="#0f172a" text-anchor="middle">{val:.4f}</text>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{mt + ph + 16}" font-family="sans-serif" font-size="10.5" fill="#334155" text-anchor="end" transform="rotate(-24 {cx:.1f} {mt + ph + 16})">{label}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def save_outputs(rows: list[dict], out_dir: Path, cases: list[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    order = [v["id"] for v in _variants()]
    summary = []
    for vid in order:
        items = [r for r in rows if r["variant"] == vid]
        summary.append(
            dict(
                variant=vid,
                group=items[0]["group"],
                runs=len(items),
                valid_runs=sum(r["valid"] for r in items),
                F=round(_date_equal_mean(items, "F"), 6),
                seed_sd=round(_seed_sd_mean(items), 6),
                T=round(_date_equal_mean(items, "T"), 3),
                R=round(_date_equal_mean(items, "R"), 3),
                D=round(_date_equal_mean(items, "D"), 3),
                p90=round(_date_equal_mean(items, "p90"), 3),
                cpu=round(_date_equal_mean(items, "cpu"), 3),
            )
        )

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)

    pairs_to_check = [
        ("wide", "simple"),
        ("gate", "wide"),
        ("hga", "gate"),
        ("hungarian", "gate"),
        ("gate", "eta"),
        ("gate", "fcfs"),
        ("gate_preview3", "gate"),
        ("gate_gen8", "gate"),
        ("gate_gen24", "gate"),
        ("wide_adapt01", "wide_adapt00"),
        ("wide_adapt11", "wide_adapt00"),
        ("hga_adapt01", "hga"),
        ("hga_adapt01", "gate"),
    ]
    paired_rows = []
    for cand, ref in pairs_to_check:
        pct, wins, ties, losses = _paired_pct(rows, cand, ref)
        paired_rows.append(
            dict(
                candidate=cand,
                baseline=ref,
                mean_F_improve_pct=round(pct, 4),
                wins=wins,
                ties=ties,
                losses=losses,
            )
        )

    with (out_dir / "paired.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(paired_rows[0].keys()))
        writer.writeheader()
        writer.writerows(paired_rows)

    evo_palette = ["#64748b", "#0284c7", "#0d9488", "#9333ea", "#2563eb", "#1d4ed8", "#15803d"]
    (fig_dir / "validation_evolution.svg").write_text(
        _svg_bars(
            "WEPA Held-Out Validation Split: 7-Method Evolution",
            "4 unseen validation windows (day40, day61, day83, day87), equal-weighted by date",
            [
                (r["variant"], r["F"], r["seed_sd"], evo_palette[i % len(evo_palette)])
                for i, r in enumerate(summary)
                if r["group"] == "evolution"
            ],
            "Linear Objective F (lower is better)",
        ),
        encoding="utf-8",
    )
    (fig_dir / "validation_budget_and_adaptive.svg").write_text(
        _svg_bars(
            "WEPA Validation Split: Budget Bounds, Adaptive GA & HGA+Adaptive01",
            "Seeds 0..2 across 4 unseen validation windows (day40, day61, day83, day87)",
            [
                (
                    r["variant"],
                    r["F"],
                    r["seed_sd"],
                    "#0284c7"
                    if r["group"] == "budget"
                    else "#059669"
                    if r["group"] == "adaptive"
                    else "#b91c1c"
                    if r["variant"] == "hga_adapt01"
                    else "#1d4ed8",
                )
                for r in summary
                if r["variant"]
                in (
                    "gate",
                    "hga",
                    "gate_preview3",
                    "gate_gen8",
                    "gate_gen24",
                    "wide_adapt00",
                    "wide_adapt01",
                    "wide_adapt11",
                    "hga_adapt01",
                )
            ],
            "Linear Objective F (lower is better)",
        ),
        encoding="utf-8",
    )

    payload = dict(
        study_id="wepa-validation-sensitivity-20261121",
        cases=cases,
        total_runs=len(rows),
        valid_runs=sum(r["valid"] for r in rows),
        summary=summary,
        paired=paired_rows,
    )
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md = [
        "# WEPA 未见验证集（Validation Split）多 Seed 与组合补充实验",
        "",
        f"- 验证窗口：`{cases}`（共 199 条真实请求，覆盖 day40 / day61 / day83 / day87）。",
        f"- 有效完成：**{sum(r['valid'] for r in rows)} / {len(rows)}**（全部通过 `checked_score` 独立验解）。",
        "",
        "## 各方案汇总（按来源日期等权）",
        "",
        "| 组别 | 方案 | 次数 | F | seed SD | T (s) | R (s) | D (cells) | P90 (s) | CPU (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary:
        md.append(
            f"| {r['group']} | `{r['variant']}` | {r['runs']} | {r['F']:.6f} | {r['seed_sd']:.5f} | "
            f"{r['T']:.2f} | {r['R']:.2f} | {r['D']:.1f} | {r['p90']:.2f} | {r['cpu']:.3f} |"
        )
    md.extend(
        [
            "",
            "## 同窗口/同 Seed 配对改善率",
            "",
            "| 候选 | 基线 | 日期等权平均 F 改善 | 胜/平/负日期 |",
            "|---|---|---:|---:|",
        ]
    )
    for p in paired_rows:
        md.append(
            f"| `{p['candidate']}` | `{p['baseline']}` | {p['mean_F_improve_pct']:+.4f}% | {p['wins']}/{p['ties']}/{p['losses']} |"
        )
    md.extend(
        [
            "",
            "## 验证集对比图",
            "",
            "![Validation Evolution](figures/validation_evolution.svg)",
            "![Validation Budget & Adaptive](figures/validation_budget_and_adaptive.svg)",
        ]
    )
    (out_dir / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    proto = json.loads((args.runtime / "data/protocol.json").read_text(encoding="utf-8"))
    val_cases = list(proto["validation"])
    jobs = []
    for variant in _variants():
        for case in val_cases:
            for seed in variant["seeds"]:
                jobs.append(
                    dict(
                        id=f"{case}__{variant['id']}__s{seed}",
                        case=case,
                        seed=seed,
                        variant_spec=variant,
                        runtime=str(args.runtime),
                    )
                )
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_worker, jobs))
    payload = save_outputs(rows, args.output, val_cases)
    print(
        json.dumps(
            dict(
                output=str(args.output),
                total_runs=payload["total_runs"],
                valid_runs=payload["valid_runs"],
                wall_seconds=round(time.perf_counter() - t0, 2),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
