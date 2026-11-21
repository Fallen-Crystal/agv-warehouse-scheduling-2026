#!/usr/bin/env python3
"""Multi-seed evolution and hyperparameter sensitivity study on core src/agv planners."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from agv.api import generate_scene
from agv.dispatch.bcrd import run as run_bcrd
from agv.dispatch.optimized import run as run_optimized
from agv.dispatch.registry import run_named
from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results/core-sensitivity-20261121"


def _run_job(spec: dict) -> dict:
    profile = spec["profile"]
    mode = spec["mode"]
    seed = spec["seed"]
    kwargs = dict(spec["scene_kwargs"])
    scenario = generate_scene(profile=profile, mode=mode, seed=seed, **kwargs)
    t0 = time.perf_counter()
    cpu0 = time.process_time()
    runner = spec["runner"]
    if runner == "named":
        result = run_named(spec["solver"], scenario)
    elif runner == "optimized":
        result = run_optimized(scenario, **spec["params"])
        if scenario.uses_layer_rules:
            result = score_result(scenario, result)
    elif runner == "bcrd":
        result = run_bcrd(scenario, **spec["params"])
        if scenario.uses_layer_rules:
            result = score_result(scenario, result)
    else:
        raise ValueError(f"Unknown runner: {runner}")
    cpu = time.process_time() - cpu0
    wall = time.perf_counter() - t0
    validate(scenario, result)
    return {
        "group": spec["group"],
        "profile": profile,
        "mode": mode,
        "variant": spec["variant"],
        "param_name": spec.get("param_name", ""),
        "param_value": spec.get("param_value", ""),
        "seed": seed,
        "feasible": bool(result["feasible"]),
        "completed": int(result["completed"]),
        "total_tasks": int(result["total_tasks"]),
        "makespan": float(result["makespan"]),
        "mean_flow_time": float(result["mean_flow_time"]),
        "p90_flow_time": float(result.get("p90_flow_time", 0.0)),
        "moves": int(result["moves"]),
        "empty_moves": int(result.get("empty_moves", 0)),
        "traffic_wait_steps": int(result.get("traffic_wait_steps", 0)),
        "weighted_score": (
            float(result["weighted_score"]) if result.get("weighted_score") is not None else None
        ),
        "cpu_seconds": round(cpu, 6),
        "wall_seconds": round(wall, 6),
    }


def _build_specs(seeds: list[int]) -> list[dict]:
    specs = []
    legacy_scene = dict(
        size="medium", vehicles=6, task_count=24, layout="bottleneck", arrival="burst"
    )
    for mode, solvers in (
        (
            "static",
            (
                "baseline",
                "joint_only",
                "joint_batch",
                "sipp_joint",
                "sipp_conflict",
                "sipp_budget",
                "sipp_batch",
                "sipp_learned",
            ),
        ),
        (
            "dynamic",
            (
                "baseline",
                "joint_only",
                "sipp_joint",
                "sipp_conflict",
                "sipp_budget",
                "sipp_learned",
            ),
        ),
    ):
        for solver in solvers:
            for seed in seeds:
                specs.append(
                    dict(
                        group=f"legacy_{mode}_evolution",
                        profile="legacy",
                        mode=mode,
                        scene_kwargs=legacy_scene,
                        runner="named",
                        solver=solver,
                        variant=solver,
                        seed=seed,
                    )
                )

    for budget in (2, 4, 6, 10):
        for seed in seeds:
            specs.append(
                dict(
                    group="legacy_dynamic_trial_budget",
                    profile="legacy",
                    mode="dynamic",
                    scene_kwargs=legacy_scene,
                    runner="optimized",
                    params=dict(
                        assignment="greedy",
                        joint=True,
                        router_kind="sipp",
                        neighborhoods="conflict",
                        trial_budget=budget,
                    ),
                    variant=f"sipp_conflict_b{budget}",
                    param_name="trial_budget",
                    param_value=budget,
                    seed=seed,
                )
            )

    for interval in (2, 5, 10):
        for seed in seeds:
            specs.append(
                dict(
                    group="legacy_dynamic_interval",
                    profile="legacy",
                    mode="dynamic",
                    scene_kwargs=legacy_scene,
                    runner="optimized",
                    params=dict(
                        assignment="greedy",
                        joint=True,
                        interval=interval,
                        router_kind="sipp",
                        neighborhoods="conflict",
                        trial_budget=6,
                    ),
                    variant=f"sipp_budget_int{interval}",
                    param_name="interval",
                    param_value=interval,
                    seed=seed,
                )
            )

    v4_scene = dict(size="small", vehicles=6, task_count=18, shelf_layers=3, arrival="burst")
    for solver in ("baseline", "sipp_budget", "sipp_matching", "bcrd_budget"):
        for seed in seeds:
            specs.append(
                dict(
                    group="v4_dynamic_evolution",
                    profile="v4",
                    mode="dynamic",
                    scene_kwargs=v4_scene,
                    runner="named",
                    solver=solver,
                    variant=solver,
                    seed=seed,
                )
            )

    v91_scene = dict(size="medium", vehicles=4, task_count=16, shelf_layers=5, arrival="burst")
    for solver in (
        "baseline",
        "sipp_stream_dispatch",
        "sipp_stream_matching",
        "sipp_position_dispatch",
        "sipp_stream_bcrd",
        "sipp_stream_bcrd_tail",
    ):
        for seed in seeds:
            specs.append(
                dict(
                    group="v91_dynamic_evolution",
                    profile="v9.1",
                    mode="dynamic",
                    scene_kwargs=v91_scene,
                    runner="named",
                    solver=solver,
                    variant=solver,
                    seed=seed,
                )
            )

    for max_batches in (1, 2, 4, 6):
        for seed in seeds:
            specs.append(
                dict(
                    group="v91_bcrd_max_batches",
                    profile="v9.1",
                    mode="static",
                    scene_kwargs=v91_scene,
                    runner="bcrd",
                    params=dict(policy="bcrd", max_batches=max_batches),
                    variant=f"v91_bcrd_m{max_batches}",
                    param_name="max_batches",
                    param_value=max_batches,
                    seed=seed,
                )
            )

    for solver in (
        "baseline",
        "sipp_stream_dispatch",
        "sipp_stream_matching",
        "sipp_position_dispatch",
        "sipp_stream_bcrd",
        "sipp_stream_bcrd_tail",
    ):
        for seed in seeds:
            specs.append(
                dict(
                    group="v91_static_evolution",
                    profile="v9.1",
                    mode="static",
                    scene_kwargs=v91_scene,
                    runner="named",
                    solver=solver,
                    variant=solver,
                    seed=seed,
                )
            )

    return specs


def _stats(rows: list[dict], key: str) -> tuple[float | None, float | None]:
    vals = [r[key] for r in rows if r[key] is not None]
    if not vals:
        return None, None
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd


def _svg_bar_chart(
    title: str, subtitle: str, items: list[tuple[str, float, float, str]], y_label: str
) -> str:
    w, h = 820, 360
    ml, mr, mt, mb = 75, 25, 65, 95
    pw, ph = w - ml - mr, h - mt - mb
    max_val = max((v + sd for _, v, sd, _ in items), default=1.0)
    min_val = min((v - sd for _, v, sd, _ in items), default=0.0)
    lo = 0.0 if min_val >= 0 else min_val * 1.1
    hi = max_val * 1.12 if max_val > lo else lo + 1.0
    span = hi - lo

    def y_px(val: float) -> float:
        return mt + ph - ((val - lo) / span) * ph

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{ml}" y="26" font-family="sans-serif" font-size="16" font-weight="bold" fill="#1e293b">{title}</text>',
        f'<text x="{ml}" y="46" font-family="sans-serif" font-size="12" fill="#64748b">{subtitle}</text>',
        f'<text x="18" y="{mt + ph / 2:.1f}" font-family="sans-serif" font-size="12" fill="#334155" transform="rotate(-90 18 {mt + ph / 2:.1f})" text-anchor="middle">{y_label}</text>',
    ]
    for step in range(5):
        val = lo + span * step / 4
        yp = y_px(val)
        lines.append(
            f'<line x1="{ml}" y1="{yp:.1f}" x2="{w - mr}" y2="{yp:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        )
        lines.append(
            f'<text x="{ml - 8}" y="{yp + 4:.1f}" font-family="sans-serif" font-size="11" fill="#475569" text-anchor="end">{val:.2f}</text>'
        )
    lines.append(
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="#334155" stroke-width="1.2"/>'
    )
    lines.append(
        f'<line x1="{ml}" y1="{mt + ph}" x2="{w - mr}" y2="{mt + ph}" stroke="#334155" stroke-width="1.2"/>'
    )

    slot = pw / max(1, len(items))
    bar_w = min(46.0, slot * 0.58)
    for i, (label, val, sd, color) in enumerate(items):
        cx = ml + slot * (i + 0.5)
        x0 = cx - bar_w / 2
        y0 = y_px(val)
        yb = y_px(lo)
        bh = max(1.0, yb - y0)
        lines.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{color}"/>'
        )
        if sd > 0 and not math.isnan(sd):
            yt, ybot = y_px(val + sd), y_px(max(lo, val - sd))
            lines.append(
                f'<line x1="{cx:.1f}" y1="{yt:.1f}" x2="{cx:.1f}" y2="{ybot:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
            lines.append(
                f'<line x1="{cx - 5:.1f}" y1="{yt:.1f}" x2="{cx + 5:.1f}" y2="{yt:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
            lines.append(
                f'<line x1="{cx - 5:.1f}" y1="{ybot:.1f}" x2="{cx + 5:.1f}" y2="{ybot:.1f}" stroke="#0f172a" stroke-width="1.3"/>'
            )
        lines.append(
            f'<text x="{cx:.1f}" y="{y0 - 6:.1f}" font-family="sans-serif" font-size="10.5" font-weight="bold" fill="#0f172a" text-anchor="middle">{val:.2f}</text>'
        )
        lines.append(
            f'<text x="{cx:.1f}" y="{mt + ph + 16}" font-family="sans-serif" font-size="10.5" fill="#334155" text-anchor="end" transform="rotate(-24 {cx:.1f} {mt + ph + 16})">{label}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def summarize_and_save(rows: list[dict], out_dir: Path, seeds: list[int]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys())
    with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["group"], row["variant"]), []).append(row)

    summary_rows = []
    for (group, variant), items in grouped.items():
        flow_m, flow_sd = _stats(items, "mean_flow_time")
        mk_m, mk_sd = _stats(items, "makespan")
        mv_m, _ = _stats(items, "moves")
        cpu_m, _ = _stats(items, "cpu_seconds")
        ws_m, ws_sd = _stats(items, "weighted_score")
        summary_rows.append(
            dict(
                group=group,
                variant=variant,
                runs=len(items),
                feasible_runs=sum(r["feasible"] for r in items),
                mean_flow_time=round(flow_m, 4) if flow_m is not None else None,
                flow_sd=round(flow_sd, 4) if flow_sd is not None else None,
                makespan=round(mk_m, 4) if mk_m is not None else None,
                makespan_sd=round(mk_sd, 4) if mk_sd is not None else None,
                moves=round(mv_m, 2) if mv_m is not None else None,
                weighted_score=round(ws_m, 6) if ws_m is not None else None,
                weighted_score_sd=round(ws_sd, 6) if ws_sd is not None else None,
                cpu_seconds=round(cpu_m, 4) if cpu_m is not None else None,
            )
        )

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    def lookup(group: str) -> list[dict]:
        return [r for r in summary_rows if r["group"] == group]

    palette = [
        "#64748b",
        "#3b82f6",
        "#0284c7",
        "#0d9488",
        "#16a34a",
        "#15803d",
        "#ca8a04",
        "#9333ea",
    ]
    charts = {
        "legacy_static_flow.svg": _svg_bar_chart(
            "Legacy Static Evolution (6 Vehicles, 24 Tasks, Seeds 0..4)",
            "Mean flow time across baseline -> joint -> SIPP -> budget -> static batch rollout",
            [
                (r["variant"], r["mean_flow_time"], r["flow_sd"], palette[i % len(palette)])
                for i, r in enumerate(lookup("legacy_static_evolution"))
            ],
            "Mean Flow Time (steps, lower is better)",
        ),
        "legacy_dynamic_flow.svg": _svg_bar_chart(
            "Legacy Dynamic Burst Evolution (6 Vehicles, 24 Tasks, Seeds 0..4)",
            "Mean flow time across solver generations",
            [
                (r["variant"], r["mean_flow_time"], r["flow_sd"], palette[i % len(palette)])
                for i, r in enumerate(lookup("legacy_dynamic_evolution"))
            ],
            "Mean Flow Time (steps, lower is better)",
        ),
        "legacy_hyperparam_sensitivity.svg": _svg_bar_chart(
            "Core Planner Hyperparameter Sensitivity (Legacy Dynamic Burst, Seeds 0..4)",
            "Left: LNS trial_budget (2,4,6,10) | Right: replanning interval (2,5,10)",
            [
                (r["variant"], r["mean_flow_time"], r["flow_sd"], "#2563eb")
                for r in lookup("legacy_dynamic_trial_budget")
            ]
            + [
                (r["variant"], r["mean_flow_time"], r["flow_sd"], "#059669")
                for r in lookup("legacy_dynamic_interval")
            ],
            "Mean Flow Time (steps, lower is better)",
        ),
        "v91_evolution_and_bcrd_batches.svg": _svg_bar_chart(
            "V9.1 Static Dense-Backlog Evolution & BCRD max_batches (4 Vehicles, 16 Tasks, Seeds 0..4)",
            "Normalized objective F (lower is better; baseline = 1.00)",
            [
                (r["variant"], r["weighted_score"], r["weighted_score_sd"], "#0284c7")
                for r in lookup("v91_static_evolution")
            ]
            + [
                (r["variant"], r["weighted_score"], r["weighted_score_sd"], "#d97706")
                for r in lookup("v91_bcrd_max_batches")
            ],
            "Normalized Weighted Score F",
        ),
    }
    for name, content in charts.items():
        (fig_dir / name).write_text(content, encoding="utf-8")

    payload = dict(
        study_id="core-multiseed-sensitivity-20261121",
        seeds=seeds,
        total_runs=len(rows),
        feasible_runs=sum(r["feasible"] for r in rows),
        summary=summary_rows,
    )
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md = [
        "# 核心引擎（src/agv）多 Seed 演进与超参数敏感性实验",
        "",
        f"- 总运行次数：**{len(rows)} / {len(rows)}** 全部通过 `validate()` 独立物理验解，全部可行（`feasible = {sum(r['feasible'] for r in rows)}/{len(rows)}`）。",
        f"- 随机种子：`{seeds}`（每个配置 5 个独立随机种子）。",
        "",
        "## 各组汇总指标",
        "",
        "| 实验组 | 方案/参数 | 次数 | 可行 | 平均 Flow Time (±SD) | Makespan (±SD) | 总移动步数 | 归一化 F (±SD) | CPU (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary_rows:
        f_str = (
            f"{r['weighted_score']:.4f} (±{r['weighted_score_sd']:.4f})"
            if r["weighted_score"] is not None
            else "-"
        )
        md.append(
            f"| {r['group']} | `{r['variant']}` | {r['runs']} | {r['feasible_runs']} | "
            f"{r['mean_flow_time']:.2f} (±{r['flow_sd']:.2f}) | {r['makespan']:.2f} (±{r['makespan_sd']:.2f}) | "
            f"{r['moves']:.1f} | {f_str} | {r['cpu_seconds']:.3f} |"
        )
    md.extend(
        [
            "",
            "## 对比图表",
            "",
            "![Legacy Static Evolution](figures/legacy_static_flow.svg)",
            "![Legacy Dynamic Evolution](figures/legacy_dynamic_flow.svg)",
            "![Legacy Hyperparameter Sensitivity](figures/legacy_hyperparam_sensitivity.svg)",
            "![V9.1 Evolution & BCRD Sensitivity](figures/v91_evolution_and_bcrd_batches.svg)",
        ]
    )
    (out_dir / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    seeds = [0, 1, 2, 3, 4]
    specs = _build_specs(seeds)
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_run_job, specs))
    payload = summarize_and_save(rows, args.output, seeds)
    print(
        json.dumps(
            dict(
                output=str(args.output),
                total_runs=payload["total_runs"],
                feasible_runs=payload["feasible_runs"],
                wall_seconds=round(time.perf_counter() - t0, 2),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
