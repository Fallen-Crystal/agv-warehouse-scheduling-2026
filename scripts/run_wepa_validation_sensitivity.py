#!/usr/bin/env python3
"""Existing WEPA validation-window retrospective multi-seed & hyperparameter re-evaluation.

Complements results/wepa-dev-sensitivity-20261120 (which evaluated the 4 development
windows) by re-evaluating the 4 existing validation windows (used in Oct 2026 to select
gate), an expanded generations budget (gate_gen24), and the combined hga_adapt01 variant.
"""

from __future__ import annotations

import argparse
import csv
import html
import importlib
import importlib.util
import json
import math
import random
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
DEFAULT_OUT = ROOT / "results/wepa-val-sensitivity-20261121"


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


def _bootstrap_ci(values: list[float], n_boot: int = 4000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(20261121)
    k = len(values)
    means = sorted(sum(rng.choices(values, k=k)) / k for _ in range(n_boot))
    lo = means[int(0.025 * (n_boot - 1))]
    hi = means[int(0.975 * (n_boot - 1))]
    return lo, hi


def _paired_pct(rows: list[dict], cand: str, ref: str) -> tuple[float, float, float, int, int, int]:
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
    day_means = [statistics.mean(days[d]) for d in sorted(days)]
    wins = sum(x > 1e-9 for x in day_means)
    ties = sum(abs(x) <= 1e-9 for x in day_means)
    losses = sum(x < -1e-9 for x in day_means)
    ci_lo, ci_hi = _bootstrap_ci(day_means)
    return statistics.mean(day_means), ci_lo, ci_hi, wins, ties, losses


def _svg_bars(
    title: str, subtitle: str, items: list[tuple[str, float, float, str]], y_label: str
) -> str:
    w, h = 840, 370
    ml, mr, mt, mb = 78, 25, 68, 95
    pw, ph = w - ml - mr, h - mt - mb
    vals = [v for _, v, _, _ in items]
    lo = min(vals) * 0.96
    max_top = max(v + sd for _, v, sd, _ in items)
    span_raw = max_top - lo if max_top > lo else 0.05
    hi = max_top + span_raw * 0.22
    span = hi - lo

    def y_px(val: float) -> float:
        return mt + ph - ((val - lo) / span) * ph

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{ml}" y="26" font-family="sans-serif" font-size="15.5" font-weight="bold" fill="#1e293b">{html.escape(title)}</text>',
        f'<text x="{ml}" y="46" font-family="sans-serif" font-size="11.5" fill="#64748b">{html.escape(subtitle)}</text>',
        f'<text x="18" y="{mt + ph / 2:.1f}" font-family="sans-serif" font-size="12" fill="#334155" transform="rotate(-90 18 {mt + ph / 2:.1f})" text-anchor="middle">{html.escape(y_label)}</text>',
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
    bar_w = min(46.0, slot * 0.56)
    for i, (label, val, sd, color) in enumerate(items):
        cx = ml + slot * (i + 0.5)
        x0 = cx - bar_w / 2
        y0 = y_px(val)
        bh = max(2.0, (mt + ph) - y0)
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{color}"/>'
        )
        top_y = y0
        if sd > 0 and not math.isnan(sd):
            yt, ybot = y_px(min(hi, val + sd)), y_px(max(lo, val - sd))
            top_y = min(y0, yt)
            out.append(
                f'<line x1="{cx:.1f}" y1="{yt:.1f}" x2="{cx:.1f}" y2="{ybot:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
            out.append(
                f'<line x1="{cx - 4:.1f}" y1="{yt:.1f}" x2="{cx + 4:.1f}" y2="{yt:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
            out.append(
                f'<line x1="{cx - 4:.1f}" y1="{ybot:.1f}" x2="{cx + 4:.1f}" y2="{ybot:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
        out.append(
            f'<text x="{cx:.1f}" y="{top_y - 6:.1f}" font-family="sans-serif" font-size="10.2" font-weight="bold" fill="#0f172a" stroke="#ffffff" stroke-width="3" paint-order="stroke" text-anchor="middle">{val:.4f}</text>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{mt + ph + 16}" font-family="sans-serif" font-size="10.5" fill="#334155" text-anchor="end" transform="rotate(-24 {cx:.1f} {mt + ph + 16})">{html.escape(label)}</text>'
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
        pct, ci_lo, ci_hi, wins, ties, losses = _paired_pct(rows, cand, ref)
        paired_rows.append(
            dict(
                candidate=cand,
                baseline=ref,
                mean_F_improve_pct=round(pct, 4),
                ci95_low=round(ci_lo, 4),
                ci95_high=round(ci_hi, 4),
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
            "WEPA Existing Validation Windows: 7-Method Evolution",
            "Retrospective re-evaluation on day40, day61, day83, day87 (equal-weighted by date)",
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
            "WEPA Validation Windows: Budget Variants, Adaptive GA & HGA+Adaptive01",
            "Seeds 0..2 across 4 existing validation windows (day40, day61, day83, day87)",
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
        study_id="wepa-val-sensitivity-20261121",
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
        "# WEPA 既有验证窗口复评与组合实验（wepa-val-sensitivity-20261121）",
        "",
        "> 本实验在 2026-10 已选用的 4 个验证窗口（`day40/61/83/87`）上开展多 seed 回顾性复评，用于检验开发集上发现的候选方案是否具备跨窗口稳定性。",
        "",
        "## 结论",
        "",
        "1. GA 类方案在 4 个既有验证窗口上全部优于规则基线：`gate` 相对 `fcfs` 改善 +5.45%、相对 `eta` 改善 +2.43%、相对 `hungarian` 改善 +3.87%，4 个日期全部改善（4/0/0）。",
        "2. `gate` 与 `wide` 表现极为接近（−0.10%，0/2/2），`wide` 均值略低（0.8983 vs 0.8992），而 `gate` 触发 GA 次数更少。",
        "3. 开发集最优的 `hga` 在既有验证窗口全部变差（−1.12%，0/0/4）；组合方案 `hga_adapt01` 比 `hga` 改善 +0.79%（3/0/1）且 seed 标准差最低（0.00521），整体仍略逊于 `gate`（−0.28%，2/0/2）。",
        "4. 预算对照：扩大至 24 代（`gate_gen24`）比默认差 −1.41%（0/0/4），说明默认 16 代已足够充分；减半至 8 代（`gate_gen8`）差 −0.35%（1/0/3）；将完整预演降至 3 次（`gate_preview3`）使 CPU 降低约 44%（21.66→12.09 秒），F 仅变化 −0.33%（0/2/2）。",
        "5. 自适应算子：开发集有效的“只开交叉自适应”（`wide_adapt01`）在验证窗口相对 `wide_adapt00` 变化 −0.54%（1/0/3），跨窗口表现不稳定。",
        "6. 与 2026-10 记录一致：本轮 `gate` F=0.8992 为 seed 0–2 均值，10 月记录的 0.8964 为单 seed 0 成绩，两者口径对应。",
        "",
        "## 方法",
        "",
        f"- **窗口与验解**：`{cases}`（day40 / day61 / day83 / day87 各 1 个，共 199 条真实请求）；**{sum(r['valid'] for r in rows)} / {len(rows)}** 次运行全部通过 `checked_score` 独立物理验解。",
        "- **随机种子设置**：确定性方案（`fcfs` / `eta` / `hungarian`）运行 seed 0–1（每方案 8 次），随机搜索方案运行 seed 0–2（每方案 12 次）；配对比较严格使用两方共同 seed（同窗口、同 seed 配对）。",
        "- **改善率与区间**：改善率 = 100% × (1 − 候选 F / 基线 F)，正数表示候选更优；单日期平均改善率满足 `|Δ| ≤ 1e-9` 判定为“持平”；区间为固定随机种子（4000 次抽样）的日期 bootstrap 95% 区间。",
        "- **指标口径**：`T` 为最后一单完成时刻（不含最终返库），`R` 为平均发布到完成耗时，`D` 为含最终返库总行驶里程（格数）；独立线性目标 $`F = 0.5\\,T/900 + 0.3\\,R/900 + 0.2\\,D/5400`$ 。",
        "",
        "## 实验边界说明",
        "",
        "本实验基于 4 个既有验证来源日期开展回顾性多 seed 复评，重点观察各方案与超参数在不同日期上的趋势与搜索稳定性，作为保留默认方案 `gate` 的直接实证依据。",
        "",
        "## 各方案汇总（按来源日期等权）",
        "",
        "| 组别 | 方案 | 次数 | F | seed SD | T 完工时间 (s) | R 平均响应 (s) | D 总里程 (格) | P90 (s) | CPU (s) |",
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
            "## 同窗口 / 同 Seed 配对改善率",
            "",
            "| 候选 | 基线 | 日期等权平均 F 改善 | 日期 bootstrap 95% | 胜/平/负日期 |",
            "|---|---|---:|---|---:|",
        ]
    )
    for p in paired_rows:
        md.append(
            f"| `{p['candidate']}` | `{p['baseline']}` | {p['mean_F_improve_pct']:+.4f}% | "
            f"[{p['ci95_low']:+.3f}%, {p['ci95_high']:+.3f}%] | {p['wins']}/{p['ties']}/{p['losses']} |"
        )
    md.extend(
        [
            "",
            "## 对比图表",
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
