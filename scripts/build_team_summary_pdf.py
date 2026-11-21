#!/usr/bin/env python3
"""Build a teammate-friendly Chinese PDF overview of the entire AGV scheduling project.

Reads frozen study summaries and vector/raster figures from:
  - results/sensitivity-20261120-v2/report/
  - results/sensitivity-20261121-validation/
  - results/core-sensitivity-20261121/

Renders clean A4 print HTML via Google Chrome headless to:
  output/pdf/AGV仓库调度项目全链路梳理与实验总结报告.pdf
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "pdf" / "AGV仓库调度项目全链路梳理与实验总结报告.pdf"
CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _svg_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{payload}"


def _png_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _fmt(val: float | str | None, digits: int = 4) -> str:
    if val is None or val == "":
        return "-"
    return f"{float(val):.{digits}f}"


def _build_roadmap_svg() -> str:
    return """<svg viewBox="0 0 820 278" width="100%" xmlns="http://www.w3.org/2000/svg"
     style="font-family:'PingFang SC','Hiragino Sans GB','Helvetica Neue',sans-serif;">
  <defs>
    <marker id="arrA" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#21617a"/>
    </marker>
    <marker id="arrB" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#297b58"/>
    </marker>
    <marker id="arrWarn" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M 0 1.5 L 8.5 5 L 0 8.5 z" fill="#9a5b13"/>
    </marker>
  </defs>

  <!-- Track A background -->
  <rect x="8" y="8" width="804" height="128" rx="10" fill="#f3f8fb" stroke="#c8dce6" stroke-width="1.2"/>
  <text x="20" y="29" font-size="12.5" font-weight="700" fill="#173442">主线 A：自研通用调度引擎 (src/agv/) —— 合成 / 分层 / 混合货架多工况 · 目标 F (V4/V9.1 归一化)</text>

  <!-- Legacy chain -->
  <rect x="20" y="42" width="102" height="38" rx="6" fill="#ffffff" stroke="#21617a" stroke-width="1.2"/>
  <text x="71" y="59" text-anchor="middle" font-size="11" font-weight="700" fill="#173442">baseline</text>
  <text x="71" y="73" text-anchor="middle" font-size="9.5" fill="#53636c">距离贪心 + A*</text>

  <line x1="122" y1="61" x2="144" y2="61" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="148" y="42" width="128" height="38" rx="6" fill="#ffffff" stroke="#21617a" stroke-width="1.2"/>
  <text x="212" y="59" text-anchor="middle" font-size="10.8" font-weight="700" fill="#173442">joint_only / batch</text>
  <text x="212" y="73" text-anchor="middle" font-size="9.5" fill="#53636c">LNS 联合修复 / 静态批滚动</text>

  <line x1="276" y1="61" x2="298" y2="61" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="302" y="42" width="152" height="38" rx="6" fill="#e6f2f7" stroke="#21617a" stroke-width="1.4"/>
  <text x="378" y="59" text-anchor="middle" font-size="10.8" font-weight="700" fill="#173442">sipp_joint → conflict</text>
  <text x="378" y="73" text-anchor="middle" font-size="9.5" fill="#21617a">安全区间压缩 + 拥堵对重排</text>

  <line x1="454" y1="61" x2="476" y2="61" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="480" y="42" width="156" height="38" rx="6" fill="#d9eef7" stroke="#173442" stroke-width="1.6"/>
  <text x="558" y="59" text-anchor="middle" font-size="10.8" font-weight="700" fill="#173442">sipp_budget / batch</text>
  <text x="558" y="73" text-anchor="middle" font-size="9.5" fill="#173442">6 候选预算 / 静态首轮优化</text>

  <line x1="636" y1="61" x2="658" y2="61" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="662" y="42" width="136" height="38" rx="6" fill="#ffffff" stroke="#53636c" stroke-width="1.2"/>
  <text x="730" y="59" text-anchor="middle" font-size="10.8" font-weight="700" fill="#173442">sipp_learned</text>
  <text x="730" y="73" text-anchor="middle" font-size="9.5" fill="#53636c">8 特征岭回归排序</text>

  <!-- V4 -> V9 -> V9.1 branch -->
  <path d="M 558 80 L 558 92 L 195 92 L 195 98" fill="none" stroke="#21617a" stroke-width="1.3"/>
  <rect x="92" y="96" width="186" height="32" rx="6" fill="#ffffff" stroke="#21617a" stroke-width="1.2"/>
  <text x="185" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V4 分层货架 + bcrd_budget</text>
  <text x="185" y="123" text-anchor="middle" font-size="9" fill="#21617a">影子试派多批序列 (-3.01% F)</text>

  <line x1="278" y1="112" x2="314" y2="112" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="318" y="96" width="174" height="32" rx="6" fill="#ffffff" stroke="#21617a" stroke-width="1.2"/>
  <text x="405" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V9 混合背靠背 + 定位待命</text>
  <text x="405" y="123" text-anchor="middle" font-size="9" fill="#53636c">安全待命点 + 动态定位</text>

  <line x1="492" y1="112" x2="524" y2="112" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="528" y="96" width="270" height="32" rx="6" fill="#d9eef7" stroke="#173442" stroke-width="1.5"/>
  <text x="663" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V9.1 流式关闭 + BCRD 尾保护</text>
  <text x="663" y="123" text-anchor="middle" font-size="9" fill="#173442">高负载 max_batches≥2 解锁 -1.5% F</text>

  <!-- Track B background -->
  <rect x="8" y="144" width="804" height="126" rx="10" fill="#f3faf6" stroke="#c3e0d1" stroke-width="1.2"/>
  <text x="20" y="165" font-size="12.5" font-weight="700" fill="#16402e">主线 B：WEPAStacks 真实订单流研究 (research/) —— 62×47 大地图 / 6 车 / 5 层 / 900s 窗口 · 独立线性目标 F</text>

  <rect x="20" y="178" width="110" height="38" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="75" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#16402e">fcfs / eta</text>
  <text x="75" y="209" text-anchor="middle" font-size="9.5" fill="#53636c">规则基线 (0.5~0.6s)</text>

  <line x1="130" y1="197" x2="152" y2="197" stroke="#297b58" stroke-width="1.5" marker-end="url(#arrB)"/>

  <rect x="156" y="178" width="128" height="38" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="220" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#16402e">simple → wide</text>
  <text x="220" y="209" text-anchor="middle" font-size="9.5" fill="#53636c">早期GA → 扩预算GA</text>

  <line x1="284" y1="197" x2="306" y2="197" stroke="#297b58" stroke-width="1.5" marker-end="url(#arrB)"/>

  <rect x="310" y="178" width="176" height="38" rx="6" fill="#dcf2e7" stroke="#16402e" stroke-width="1.8"/>
  <text x="398" y="195" text-anchor="middle" font-size="11" font-weight="700" fill="#16402e">gate (推荐默认方案)</text>
  <text x="398" y="209" text-anchor="middle" font-size="9.5" fill="#16402e">门控联合 GA + SIPP 物理预演</text>

  <line x1="486" y1="197" x2="510" y2="197" stroke="#9a5b13" stroke-width="1.5" marker-end="url(#arrWarn)"/>

  <rect x="514" y="178" width="144" height="38" rx="6" fill="#fff8eb" stroke="#c8832c" stroke-width="1.3"/>
  <text x="586" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#7a4508">hungarian → hga</text>
  <text x="586" y="209" text-anchor="middle" font-size="9.2" fill="#9a5b13">开发集最优 / 验证集回退</text>

  <line x1="486" y1="205" x2="510" y2="239" stroke="#297b58" stroke-width="1.4" marker-end="url(#arrB)"/>

  <rect x="20" y="226" width="236" height="34" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="138" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#16402e">gate_preview3 (算力受限优选)</text>
  <text x="138" y="254" text-anchor="middle" font-size="9" fill="#297b58">CPU 降 44%~45%，质量接近 gate</text>

  <rect x="272" y="226" width="214" height="34" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="379" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#16402e">dqn-experiment-v2 (源码已整理)</text>
  <text x="379" y="254" text-anchor="middle" font-size="9" fill="#53636c">自适应 pm/pc + Double DQN 动作选择</text>

  <rect x="502" y="226" width="296" height="34" rx="6" fill="#f0f7f4" stroke="#297b58" stroke-width="1.2"/>
  <text x="650" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#16402e">hga_adapt01 (新验证集组合发现)</text>
  <text x="650" y="254" text-anchor="middle" font-size="9" fill="#16402e">仅开交叉自适应：拉回 hga +0.79% 且 seed SD 最低</text>
</svg>"""


def build_html() -> str:
    dev_summary = {
        row["variant"]: row
        for row in _load_csv(
            ROOT / "results" / "sensitivity-20261120-v2" / "report" / "summary.csv"
        )
    }
    val_data = _load_json(ROOT / "results" / "sensitivity-20261121-validation" / "summary.json")
    val_summary = {row["variant"]: row for row in val_data["summary"]}
    val_paired = {f"{r['candidate']}_vs_{r['baseline']}": r for r in val_data["paired"]}

    core_data = _load_json(ROOT / "results" / "core-sensitivity-20261121" / "summary.json")
    core_rows = core_data["summary"]

    # Dev paired ratios from Codex's Chinese report table (confirmed in summary)
    dev_paired_map = {
        "wide_vs_simple": "+0.988% (3/1/0)",
        "gate_vs_wide": "+0.112% (1/3/0)",
        "hga_vs_gate": "+0.946% (2/1/1)",
        "hungarian_vs_gate": "-1.285% (0/1/3)",
        "gate_vs_eta": "+2.753% (3/0/1)",
        "gate_vs_fcfs": "+4.301% (3/0/1)",
        "gate_preview3_vs_gate": "-0.683% (0/2/2)",
        "gate_gen8_vs_gate": "-1.041% (1/1/2)",
        "gate_gen24_vs_gate": "未测 (新增于验证集)",
        "wide_adapt01_vs_wide_adapt00": "+0.938% (3/1/0)",
        "wide_adapt11_vs_wide_adapt00": "+0.234% (2/0/2)",
        "hga_adapt01_vs_hga": "未测 (新增于验证集)",
    }

    wepa_compare_specs = [
        ("fcfs", "先到先服务规则", "gate_vs_fcfs"),
        ("eta", "最早到达局部估算", "gate_vs_eta"),
        ("hungarian", "匈牙利纯局部指派", "hungarian_vs_gate"),
        ("simple", "早期 GA 基线", "wide_vs_simple"),
        ("wide", "扩预算联合 GA", "wide_vs_simple"),
        ("gate", "推荐默认：门控+SIPP", "gate_vs_wide"),
        ("hga", "匈牙利初始化 GA", "hga_vs_gate"),
        ("gate_preview3", "预演上限=3 (降耗)", "gate_preview3_vs_gate"),
        ("gate_gen8", "演化代数=8 (减半)", "gate_gen8_vs_gate"),
        ("gate_gen24", "演化代数=24 (上界)", "gate_gen24_vs_gate"),
        ("wide_adapt00", "移植GA 无自适应", None),
        ("wide_adapt01", "仅开启交叉自适应", "wide_adapt01_vs_wide_adapt00"),
        ("wide_adapt11", "交叉+变异双自适应", "wide_adapt11_vs_wide_adapt00"),
        ("hga_adapt01", "HGA+仅交叉自适应", "hga_adapt01_vs_hga"),
    ]

    wepa_rows_html = []
    for key, desc, pair_key in wepa_compare_specs:
        d = dev_summary.get(key)
        v = val_summary.get(key)
        d_f = _fmt(d["F"], 4) if d else "未测"
        d_sd = _fmt(d["F_seed_sd_mean"], 4) if d else "-"
        d_cpu = _fmt(d["cpu"], 2) if d else "-"
        v_f = _fmt(v["F"], 4) if v else "未测"
        v_sd = _fmt(v["seed_sd"], 4) if v else "-"
        v_cpu = _fmt(v["cpu"], 2) if v else "-"
        vp = val_paired.get(pair_key) if pair_key else None
        if vp:
            vp_str = f"{vp['mean_F_improve_pct']:+.3f}% ({vp['wins']}/{vp['ties']}/{vp['losses']})"
        else:
            vp_str = "-"
        dp_str = dev_paired_map.get(pair_key, "-") if pair_key else "-"
        row_cls = ""
        if key == "gate":
            row_cls = ' class="hl-good"'
        elif key in ("hga", "gate_gen24", "wide_adapt01"):
            row_cls = ' class="hl-warn"'
        elif key == "hga_adapt01":
            row_cls = ' class="hl-info"'
        wepa_rows_html.append(
            f"<tr{row_cls}>"
            f"<td><code>{html.escape(key)}</code></td>"
            f"<td>{html.escape(desc)}</td>"
            f"<td class='num'>{d_f}</td>"
            f"<td class='num'>{d_sd}</td>"
            f"<td class='num'>{d_cpu}</td>"
            f"<td class='num'>{v_f}</td>"
            f"<td class='num'>{v_sd}</td>"
            f"<td class='num'>{v_cpu}</td>"
            f"<td class='num'>{html.escape(dp_str)}</td>"
            f"<td class='num'>{html.escape(vp_str)}</td>"
            "</tr>"
        )

    def _core_rows(group_names: tuple[str, ...]) -> str:
        group_labels = {
            "legacy_static_evolution": "Legacy 静态 (6车24任务)",
            "legacy_dynamic_evolution": "Legacy 动态 (6车24任务)",
            "legacy_dynamic_trial_budget": "参数: trial_budget",
            "legacy_dynamic_interval": "参数: interval",
            "v4_dynamic_evolution": "V4 分层动态 (3层18任务)",
            "v91_dynamic_evolution": "V9.1 混合动态 (5层16任务)",
            "v91_bcrd_max_batches": "参数: BCRD max_batches",
            "v91_static_evolution": "V9.1 混合静态 (5层16任务)",
        }
        out = []
        for row in core_rows:
            if row["group"] not in group_names:
                continue
            glabel = group_labels.get(row["group"], row["group"])
            wscore = (
                f"{row['weighted_score']:.4f} (±{row['weighted_score_sd']:.4f})"
                if row["weighted_score"] is not None
                else "-"
            )
            hl = ""
            if row["variant"] in ("sipp_batch", "sipp_budget", "bcrd_budget", "sipp_stream_bcrd"):
                hl = ' class="hl-good"'
            out.append(
                f"<tr{hl}>"
                f"<td>{html.escape(glabel)}</td>"
                f"<td><code>{html.escape(row['variant'])}</code></td>"
                f"<td class='num'>{row['mean_flow_time']:.2f} (±{row['flow_sd']:.2f})</td>"
                f"<td class='num'>{row['makespan']:.2f}</td>"
                f"<td class='num'>{row['moves']:.1f}</td>"
                f"<td class='num'>{html.escape(wscore)}</td>"
                f"<td class='num'>{row['cpu_seconds']:.3f}s</td>"
                "</tr>"
            )
        return "\n".join(out)

    val_evol_svg = _svg_data_uri(
        ROOT
        / "results"
        / "sensitivity-20261121-validation"
        / "figures"
        / "validation_evolution.svg"
    )
    val_param_svg = _svg_data_uri(
        ROOT
        / "results"
        / "sensitivity-20261121-validation"
        / "figures"
        / "validation_budget_and_adaptive.svg"
    )
    legacy_static_svg = _svg_data_uri(
        ROOT / "results" / "core-sensitivity-20261121" / "figures" / "legacy_static_flow.svg"
    )
    legacy_dyn_svg = _svg_data_uri(
        ROOT / "results" / "core-sensitivity-20261121" / "figures" / "legacy_dynamic_flow.svg"
    )
    legacy_hp_svg = _svg_data_uri(
        ROOT
        / "results"
        / "core-sensitivity-20261121"
        / "figures"
        / "legacy_hyperparam_sensitivity.svg"
    )
    v91_svg = _svg_data_uri(
        ROOT
        / "results"
        / "core-sensitivity-20261121"
        / "figures"
        / "v91_evolution_and_bcrd_batches.svg"
    )

    pareto_png = _png_data_uri(
        ROOT / "results" / "sensitivity-20261120-v2" / "report" / "figures" / "pareto.png"
    )
    paired_png = _png_data_uri(
        ROOT / "results" / "sensitivity-20261120-v2" / "report" / "figures" / "paired_effects.png"
    )
    budget_2x2_png = _png_data_uri(
        ROOT / "results" / "sensitivity-20261120-v2" / "report" / "figures" / "budget_2x2.png"
    )
    adapt_2x2_png = _png_data_uri(
        ROOT / "results" / "sensitivity-20261120-v2" / "report" / "figures" / "adaptive_2x2.png"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>AGV 仓库调度项目全链路梳理与实验总结报告</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 13mm 13mm 14mm 13mm;
    @bottom-left {{
      content: "agv-warehouse-scheduling-2026 · 项目全链路梳理与实验总结 (2026-11-21)";
      font-family: "PingFang SC", "Hiragino Sans GB", sans-serif;
      font-size: 8pt;
      color: #64748b;
    }}
    @bottom-right {{
      content: "第 " counter(page) " / " counter(pages) " 页";
      font-family: "PingFang SC", "Hiragino Sans GB", sans-serif;
      font-size: 8pt;
      color: #64748b;
    }}
  }}
  * {{
    box-sizing: border-box;
  }}
  body {{
    margin: 0;
    padding: 0;
    color: #173442;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    font-size: 9.4pt;
    line-height: 1.5;
  }}
  .hero {{
    background: linear-gradient(135deg, #123142 0%, #1d5773 100%);
    color: #ffffff;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }}
  .hero .kicker {{
    font-size: 8pt;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #b7dce9;
    margin-bottom: 4px;
  }}
  .hero h1 {{
    margin: 0 0 6px 0;
    font-size: 17.5pt;
    line-height: 1.25;
  }}
  .hero p {{
    margin: 0;
    font-size: 9pt;
    color: #e3f1f7;
  }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 12px;
  }}
  .kpi-card {{
    background: #f3f8fb;
    border: 1px solid #d1e2eb;
    border-top: 3px solid #21617a;
    border-radius: 7px;
    padding: 8px 10px;
  }}
  .kpi-card .val {{
    font-size: 14pt;
    font-weight: 700;
    color: #123142;
    line-height: 1.2;
  }}
  .kpi-card .lbl {{
    font-size: 7.9pt;
    color: #53636c;
    margin-top: 2px;
  }}
  h2 {{
    font-size: 12.2pt;
    color: #123142;
    border-left: 4px solid #21617a;
    padding-left: 8px;
    margin: 12px 0 7px 0;
    break-after: avoid;
  }}
  h3 {{
    font-size: 10.2pt;
    color: #1d5773;
    margin: 9px 0 4px 0;
    break-after: avoid;
  }}
  p {{
    margin: 0 0 6px 0;
  }}
  ul, ol {{
    margin: 3px 0 7px 0;
    padding-left: 18px;
  }}
  li {{
    margin-bottom: 3px;
  }}
  code {{
    font-family: "SFMono-Regular", Menlo, Consolas, monospace;
    font-size: 8.2pt;
    background: #eef4f7;
    padding: 1px 4px;
    border-radius: 3px;
    color: #173442;
  }}
  .callout {{
    background: #f5f9fb;
    border: 1px solid #cfdfe8;
    border-left: 4px solid #21617a;
    border-radius: 6px;
    padding: 8px 11px;
    margin: 7px 0;
    break-inside: avoid;
  }}
  .callout-warn {{
    background: #fff9ef;
    border: 1px solid #ecd5ab;
    border-left: 4px solid #b46914;
    border-radius: 6px;
    padding: 8px 11px;
    margin: 7px 0;
    break-inside: avoid;
  }}
  .callout-good {{
    background: #f2faf6;
    border: 1px solid #c3e2d2;
    border-left: 4px solid #297b58;
    border-radius: 6px;
    padding: 8px 11px;
    margin: 7px 0;
    break-inside: avoid;
  }}
  .callout b {{
    color: #123142;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 9px 0;
    font-size: 7.9pt;
    break-inside: avoid;
  }}
  th {{
    background: #1a475e;
    color: #ffffff;
    text-align: left;
    padding: 5px 6px;
    font-weight: 600;
    border: 1px solid #1a475e;
  }}
  th.num, td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  td {{
    padding: 4px 6px;
    border: 1px solid #dce6ec;
    vertical-align: middle;
  }}
  tr:nth-child(even) td {{
    background: #fafcfd;
  }}
  tr.hl-good td {{
    background: #edf8f2;
    font-weight: 600;
  }}
  tr.hl-warn td {{
    background: #fff6e8;
  }}
  tr.hl-info td {{
    background: #eef6fb;
  }}
  table.dense {{
    font-size: 7.35pt;
    margin: 4px 0 6px 0;
  }}
  table.dense th {{
    padding: 3.5px 5px;
  }}
  table.dense td {{
    padding: 2.3px 5px;
    line-height: 1.25;
  }}
  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin: 6px 0;
    break-inside: avoid;
  }}
  .fig-card {{
    border: 1px solid #d5e1e8;
    border-radius: 7px;
    padding: 7px 8px 5px 8px;
    background: #ffffff;
    break-inside: avoid;
    margin-bottom: 8px;
  }}
  .fig-card img {{
    width: 100%;
    height: auto;
    display: block;
  }}
  .fig-cap {{
    font-size: 7.8pt;
    color: #53636c;
    margin-top: 4px;
    line-height: 1.35;
  }}
  .page-break {{
    page-break-before: always;
    break-before: page;
  }}
  pre {{
    margin: 4px 0 8px 0;
    background: #f4f7f9;
    border: 1px solid #d8e2e8;
    border-radius: 6px;
    padding: 7px 9px;
    font-family: "SFMono-Regular", Menlo, Consolas, monospace;
    font-size: 7.6pt;
    line-height: 1.42;
    white-space: pre-wrap;
    break-inside: avoid;
  }}
</style>
</head>
<body>

<!-- PAGE 1: OVERVIEW & ENGINEERING AUDIT -->
<div class="hero">
  <div class="kicker">2026 人工智能大作业 · 仓库穿梭无人车（AGV）智能调度 · 团队同步报告</div>
  <h1>项目全链路梳理、工程整理与多 Seed / 超参数对比总结报告</h1>
  <p>基于 <code>origin/main</code> 整理汇总 ｜ 覆盖 Git 核查、代码架构、561 次多 Seed 对照实验与技术报告分工指南</p>
</div>

<div class="kpi-grid">
  <div class="kpi-card">
    <div class="val">561 次</div>
    <div class="lbl">多 Seed / 超参有效运行<br>(200 开发 + 156 验证 + 205 主引擎)</div>
  </div>
  <div class="kpi-card">
    <div class="val">307 / 307</div>
    <div class="lbl">自动化测试全通过<br>(含 ruff lint &amp; 格式检查)</div>
  </div>
  <div class="kpi-card">
    <div class="val">86%</div>
    <div class="lbl">核心模块 <code>src/agv</code> 覆盖率<br>(高于 80% 工程门槛)</div>
  </div>
  <div class="kpi-card">
    <div class="val">100% 可行</div>
    <div class="lbl">全部运行通过独立物理验解<br>(碰撞/换边/层序零违例)</div>
  </div>
</div>

<h2>一、本轮工程核查结论（给队友的前置同步）</h2>

<div class="callout-good">
  <b>1. Git 推送与分支合流已全部就绪</b>：Codex 此前将代码推到了独立分支 <code>origin/codex/multiseed-sensitivity-20261120</code>（提交 <code>fe8d009</code>、<code>9520d9a</code>），因此在 GitHub 默认主页看不到变动；现已 <b>Fast-forward 合入 <code>main</code></b>，并连同本次补充的两套对比实验与新版 <code>README.md</code> 一并提交推送至 <code>origin/main</code>（最新提交 <code>2e89978</code>）。队友直接 <code>git pull origin main</code> 即可获取全部最新代码、实验与图表。
</div>

<div class="callout-warn">
  <b>2. 为什么 GitHub 提交历史曾显示 <code>✕ 0 / 8</code>？</b> 经查询 GitHub Checks API（check run <code>135809055733</code>）证实，实际报错为：<code>"The job was not started because your account is locked due to a billing issue."</code> —— 即<b>代码推送本身完全有效</b>，只是 GitHub 账号账单锁导致云端 CI Runner 未启动，并非测试不通过。本机运行全量 <code>make check</code>（307 tests）与 <code>make coverage</code>（86%）均已全绿通过。
</div>

<h3>3. 仓库架构重组与代码整理成果</h3>
<ul>
  <li><b>去除冗余并确立唯一真实状态机</b>：合并重复研究归档（保留 <code>research/recommended-20261024/</code> 114 个指纹与 ZIP CRC 校验；整理 <code>research/dqn-experiment-v2/</code> 为去重后可直接复用的自适应 GA 与 Double DQN 代码包），所有路径规划必须通过 <code>simulation.py</code> 物理验解。</li>
  <li><b>热点性能优化（保证数学等价）</b>：<code>VertexReservations</code> 增量维护最大时域，不可变地图几何缓存与轻量 <code>apply_replan</code> 状态克隆替代全量深拷贝；完成 <code>oracle.exact_static</code> 小规模精确参考与静态批滚动对齐。</li>
  <li><b>对比实验缺口核查与全面补齐</b>：Codex 原研究（<code>wepa-multiseed-sensitivity-20261120-v2</code>）仅跑了 WEPA <b>4 个开发窗</b>（200 次），缺少（1）WEPA <b>未见验证窗</b>泛化对照、（2）演化代数上界 <code>gate_gen24</code> 与组合方案 <code>hga_adapt01</code>、（3）自研主引擎 <code>src/agv/</code> 从 <code>baseline</code> 到 <code>v9.1</code> 的跨版本演化与超参数扫描。上述 3 项缺口已全部补齐并入库。</li>
</ul>

<h3>4. 整理后仓库核心目录与资产导航</h3>
<table class="dense">
  <thead>
    <tr>
      <th style="width:26%;">目录 / 文件</th>
      <th style="width:74%;">职责与关键产出</th>
    </tr>
  </thead>
  <tbody>
    <tr><td><code>src/agv/</code></td><td>自研调度核心引擎（零三方依赖）：时空规划 <code>planning/</code>、派单与 BCRD <code>dispatch/</code>、物理仿真 <code>simulation.py</code>、Web 回放 <code>web/</code>、评估与精确 Oracle <code>evaluation/</code>。</td></tr>
    <tr><td><code>research/recommended-20261024/</code></td><td>WEPA 推荐方案（GA-SIPP 门控默认 <code>gate</code>）交付与归档包，含 114 个 SHA256 与 ZIP CRC 独立校验脚本 <code>verification/verify.py</code>。</td></tr>
    <tr><td><code>research/dqn-experiment-v2/</code></td><td>去重整理后的自适应交叉/变异 GA + 匈牙利初始化 + Double DQN 源码与权重（已接入未见验证集实验）。</td></tr>
    <tr><td><code>results/sensitivity-20261120-v2/</code></td><td>WEPA 4 开发窗（<code>day12/32/33/45</code>）200 次多 Seed 与 2×2 敏感性冻结证据；PDF 见 <code>output/pdf/AGV多seed稳定性与参数敏感性研究.pdf</code>。</td></tr>
    <tr><td><code>results/sensitivity-20261121-validation/</code></td><td><b>本轮新增</b>：WEPA 4 未见验证窗（<code>day40/61/83/87</code>）156 次补充与组合实验（<code>gate_gen24</code>、<code>hga_adapt01</code>）及 SVG 对比图。</td></tr>
    <tr><td><code>results/core-sensitivity-20261121/</code></td><td><b>本轮新增</b>：主引擎 <code>src/agv/</code> 205 次跨版本演化（Legacy/V4/V9.1）与 <code>trial_budget/interval/max_batches</code> 参数扫描及 4 张 SVG。</td></tr>
    <tr><td><code>tests/</code> &amp; <code>scripts/</code></td><td>307 项单元与 CLI/Web 集成测试（86% 覆盖率）；含实验运行、物理验证、报告汇总与本 PDF 生成脚本。</td></tr>
  </tbody>
</table>

<!-- PAGE 2: DUAL-TRACK EVOLUTION -->
<div class="page-break"></div>
<h2>二、整体研究脉络：两条演进主线与口径边界</h2>
<p>整座仓库围绕同一核心问题——<b>“多任务并发下的无碰撞路径规划 + 多车任务指派”</b>——并行推进两条互补主线。写报告时务必分清两条主线各自的评价口径：</p>

<div class="fig-card" style="padding:6px;">
  {_build_roadmap_svg()}
</div>

<table>
  <thead>
    <tr>
      <th style="width:18%;">对比维度</th>
      <th style="width:41%;">主线 A：自研通用调度引擎（<code>src/agv/</code>）</th>
      <th style="width:41%;">主线 B：WEPAStacks 真实订单流（<code>research/</code>）</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>核心用途</b></td>
      <td>多场景通用实验：Legacy 规则地图、V4 多层单面货架、V9/V9.1 混合背靠背货架、静态/动态对比与精确 OracleGap 评估。</td>
      <td>大型真实仓库订单回放验证：<code>62×47</code> 地图、6 车、5 层、15 分钟（<code>900s</code>）切片窗口、静态货位映射 <code>seed=17</code>。</td>
    </tr>
    <tr>
      <td><b>代表算法</b></td>
      <td><code>baseline</code> &rarr; <code>joint_batch</code> &rarr; <code>sipp_conflict</code> &rarr; <code>sipp_budget</code> / <code>sipp_batch</code> &rarr; <code>bcrd_budget</code> &rarr; <code>v9.1</code>。</td>
      <td><code>fcfs</code> &rarr; <code>eta</code> &rarr; <code>simple</code> &rarr; <code>wide</code> &rarr; <b><code>gate</code></b>（默认）&rarr; <code>hga</code> / <code>dqn-experiment-v2</code>。</td>
    </tr>
    <tr>
      <td><b>目标函数 F 口径</b></td>
      <td><b>V4/V9.1</b> 为同场景固定基线归一化目标：<br><code>F = 0.5*(T/T_ref) + 0.3*(R/R_ref) + 0.2*(D/D_ref)</code>；Legacy 直接汇报平均 Flow Time、Makespan 与总步数。</td>
      <td>独立固定尺度线性目标（<b>越低越好</b>）：<br><code>F = 0.5*(T/900) + 0.3*(R/900) + 0.2*(D/5400)</code>（<i>T</i> 不含最终返库，<i>D</i> 含最终返库）。</td>
    </tr>
    <tr>
      <td><b>报告注意事项</b></td>
      <td colspan="2"><b>禁止跨口径混排绝对 F 值</b>：主线 A 与主线 B 的 <i>F</i> 归一化基准不同；主线 B 内部 15 分钟窗口与历史 DQN 的 30/60 分钟窗口亦不可直接横向比 <i>F</i>。</td>
    </tr>
  </tbody>
</table>

<div class="callout">
  <b>一句话帮队友看懂两套方案的关系</b>：主线 A（<code>src/agv/</code>）是你们自研的完整调度与离散时空仿真底座（涵盖 A* / SIPP / LNS / BCRD / 分层货架物理规则），主线 B（<code>research/</code>）则是将 WEPA 真实工业订单流映射进大型多层仓后，对上层任务指派元启发式（GA / 匈牙利 / 自适应算子 / DQN）的专门对比研究。两者共享物理验解约束，但场景维度与指标口径各自独立。
</div>

<!-- PAGE 3: WEPA DEV VS VALIDATION -->
<div class="page-break"></div>
<h2>三、WEPA 真实订单流：开发集（200 次）vs 未见验证集（156 次）</h2>
<p>为回应朋友对“<b>主实验基础上加多 Seed / 超参数对照 + 检查是否过拟合</b>”的要求，本轮将 Codex 的 4 开发窗（<code>day12/32/33/45</code>）扩展到了 4 个<b>完全未在开发中调参使用过的验证窗</b>（<code>day40/61/83/87</code>，共 199 条请求），并补充了演化代数上界 <code>gate_gen24</code>（24 代）与组合方案 <code>hga_adapt01</code>。</p>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{val_evol_svg}" alt="WEPA Validation Evolution"/>
    <div class="fig-cap"><b>图 1（WEPA 未见验证集 7 方案演进）</b>：在 <code>day40/61/83/87</code> 上，<code>wide</code>（0.8983）与 <code>gate</code>（0.8992）显著优于 <code>fcfs</code>/<code>eta</code>/<code>hungarian</code>，而开发集第一名 <code>hga</code> 发生明显回退。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{val_param_svg}" alt="WEPA Validation Hyperparameters"/>
    <div class="fig-cap"><b>图 2（WEPA 未见验证集预算与自适应参数）</b>：<code>gate_preview3</code> 保持接近 <code>gate</code> 的质量（-0.33%）且省 44.2% CPU；<code>hga_adapt01</code> 把 <code>hga</code> 拉回 +0.79% 且获最低 SD（0.00521）。</div>
  </div>
</div>

<table class="dense">
  <thead>
    <tr>
      <th>方案 ID</th>
      <th>定位 / 参数</th>
      <th class="num">开发 F</th>
      <th class="num">开发SD</th>
      <th class="num">开发CPU</th>
      <th class="num">验证 F</th>
      <th class="num">验证SD</th>
      <th class="num">验证CPU</th>
      <th class="num">开发配对 (胜/平/负)</th>
      <th class="num">验证配对 (胜/平/负)</th>
    </tr>
  </thead>
  <tbody>
    {"".join(wepa_rows_html)}
  </tbody>
</table>

<!-- PAGE 4: OVERFITTING INSIGHTS + WEPA DEV KEY CHARTS -->
<div class="page-break"></div>
<div class="callout-warn" style="margin-top:0;">
  <b>本实验最关键的学术发现 —— “局部代理过拟合”现象（建议在技术报告讨论部分重点展开）</b>：
  <ul>
    <li><b>开发集假象 vs 未见集真相</b>：仅看开发集时，<code>hga</code> 相对 <code>gate</code> 提升 <b>+0.946%</b>、<code>wide_adapt01</code> 相对 <code>wide_adapt00</code> 提升 <b>+0.938%</b>；但在 4 个未见验证窗上，<code>hga</code> 相对 <code>gate</code> <b>4 窗全负（-1.116%）</b>，<code>wide_adapt01</code> 亦回退 <b>-0.540%（1/0/3）</b>，说明单纯增加局部指派偏置易过拟合特定订单密度窗。</li>
    <li><b>GA 代数存在明显的“过优倒 U 形”</b>：<code>gate</code> 默认 16 代；减半至 <code>gate_gen8</code> 在开发集掉分较多（-1.041%），但加倍到 <code>gate_gen24</code> 后反而过度迎合 GA 内部轻量代理目标、偏离真实 SIPP 拥堵演化，在未见窗 <b>4/4 全负（-1.415% vs gate）</b>。</li>
    <li><b>为何双自适应不如单自适应（机理已定位）</b>：Codex 轨迹日志证实，同时打开变异与交叉自适应（<code>wide_adapt10</code>/<code>wide_adapt11</code>）时，超过 <b>86%</b> 的代数（<code>4639/5376</code> 与 <code>4640/5360</code>）变异率饱和在上限 <code>0.95</code>，退化为高频随机扰动；反观将“匈牙利启发初始化 + 仅交叉自适应”结合的 <code>hga_adapt01</code>，既能稳定收拢前期收敛方向，又能获得最低 Seed 标准差（<code>0.00521</code>）。</li>
  </ul>
</div>

<h2>四、WEPA 开发集精选对照图（来自 <code>sensitivity-20261120-v2</code> 冻结证据）</h2>
<p>以下四张高清对照图来自 Codex 跑完并经 <code>200/200</code> 物理验解的冻结证据包（完整 8 图见 <code>output/pdf/AGV多seed稳定性与参数敏感性研究.pdf</code>），可直接选入大作业“资源—质量权衡与因子交互分析”章节：</p>

<div class="two-col">
  <div class="fig-card">
    <img src="{pareto_png}" alt="Pareto frontier"/>
    <div class="fig-cap"><b>图 3：质量与算力 Pareto 前沿（共同 Seed [0,1]）</b><br>规则基线（<code>fcfs/eta/hungarian</code>）耗时 &lt;0.6s；中间效率甜点为 <code>gate_preview3</code>（仅 7.6s CPU）；<code>gate</code>/<code>hga</code> 位于高质量区。</div>
  </div>
  <div class="fig-card">
    <img src="{paired_png}" alt="Paired effects"/>
    <div class="fig-cap"><b>图 4：固定配对改善率与日期 Bootstrap 区间</b><br>所有比较均按同 case/同 seed 严格配对（禁止挑最优 seed），展示版本演进相对 <code>fcfs</code>（+4.30%）与 <code>eta</code>（+2.75%）的稳定增益。</div>
  </div>
</div>

<div class="two-col">
  <div class="fig-card">
    <img src="{budget_2x2_png}" alt="Budget 2x2"/>
    <div class="fig-cap"><b>图 5：代理预算 × 完整预演（<code>proxy × preview</code>）2×2 交互</b><br>证明缩短完整 SIPP <code>preview</code>（6 &rarr; 3）几乎不损失求解稳定性却能直接削减 <b>45.28%</b> CPU 时间，是性价比最高的加速开关。</div>
  </div>
  <div class="fig-card">
    <img src="{adapt_2x2_png}" alt="Adaptive 2x2"/>
    <div class="fig-cap"><b>图 6：自适应交叉 × 变异（<code>pc × pm</code>）2×2 因子分解</b><br>控制同一移植 GA 实现后，开发集上仅开启交叉自适应（<code>wide_adapt01</code>）明显优于同时开启导致 <code>pm</code> 触顶的 <code>wide_adapt11</code>。</div>
  </div>
</div>

<div class="callout-good">
  <b>WEPA 主线最终定型建议</b>：技术报告的主推荐算法继续保持 <b><code>gate</code></b>（全量开发+验证双集综合最稳健，且物理可行、零调参过拟合风险）；如果现场/边缘节点算力受限，可将 <b><code>gate_preview3</code></b> 作为推荐轻量档（CPU 省 44%–45%，目标函数差距 &lt;0.7%）。
</div>

<!-- PAGE 5: CORE ENGINE EVOLUTION -->
<div class="page-break"></div>
<h2>五、自研主引擎（<code>src/agv/</code>）跨版本演进对比（205 次 / 5 Seeds）</h2>
<p>Codex 原研究未覆盖 <code>src/agv/</code> 主仓库演进链条。本次新建 <code>scripts/run_core_sensitivity.py</code>，在统一的 <code>seeds=[0,1,2,3,4]</code> 下系统测评了从最初 <code>baseline</code> 到最新 <code>v9.1</code> 的 <b>41 组配置 × 5 seeds = 205 次</b>运行，<b>205/205 全部通过 <code>validate()</code></b>。</p>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_static_svg}" alt="Legacy static evolution"/>
    <div class="fig-cap"><b>图 7：Legacy 静态场景演进</b><br>从贪心 <code>baseline</code> 演进到 <code>sipp_batch</code>，平均 Flow 下降 2.62%（50.82 &rarr; 49.49），Makespan 由 114.60 降至 109.40，总步数减少 4.24%。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_dyn_svg}" alt="Legacy dynamic evolution"/>
    <div class="fig-cap"><b>图 8：Legacy 动态到达演进</b><br><code>sipp_conflict</code> 与 <code>sipp_budget</code> 同等压缩等待（Flow 28.84 &rarr; 27.81/27.82，-3.57%），而 <code>sipp_budget</code> 省耗时 36.7%。</div>
  </div>
</div>

<table class="dense">
  <thead>
    <tr>
      <th>实验组别</th>
      <th>调度算法</th>
      <th class="num">平均 Flow (±SD)</th>
      <th class="num">Makespan</th>
      <th class="num">总移动步数</th>
      <th class="num">归一化 F (±SD)</th>
      <th class="num">平均 CPU</th>
    </tr>
  </thead>
  <tbody>
    {_core_rows(("legacy_static_evolution", "legacy_dynamic_evolution", "v4_dynamic_evolution"))}
  </tbody>
</table>

<div class="callout">
  <b>核心引擎演进阶段解读（直接对应源码各阶段改进）</b>：
  <ul>
    <li><b>Stage 1（A* + LNS 联合重排 &rarr; SIPP 安全区间）</b>：单纯把碰撞车做联合 A* 规划（<code>joint_only</code>）已能消除静态僵局；引入 SIPP 区间压缩与拥堵对优先修复（<code>sipp_conflict</code>）后，在不损失解质量的前提下显著减少了无效重搜路径。</li>
    <li><b>Stage 2（预算限流 &rarr; 静态首轮批次滚动）</b>：动态工况选 <code>sipp_budget</code> 可用 ~0.98s CPU 拿到与高预算几乎相同的 Flow；静态全已知任务采用 <code>sipp_batch</code> 枚举首轮批次序列，进一步把总行驶步数压低到全场最低 <code>596.4</code>。</li>
    <li><b>Stage 3（V4 分层货架 + BCRD 影子试派）</b>：面对多层同巷道先后顺序约束，<code>bcrd_budget</code> 在影子环境中试派多套批次顺序，比 <code>baseline</code> 将综合目标 <i>F</i> 压低 <b>3.01%</b>（Makespan <code>139.60 &rarr; 132.80</code>），仅增加不到 0.07s 计算耗时。</li>
  </ul>
</div>

<!-- PAGE 6: CORE ENGINE HYPERPARAMS & V9.1 -->
<div class="page-break"></div>
<h2>六、自研主引擎超参数敏感性与 V9.1 混合货架分析</h2>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_hp_svg}" alt="Legacy hyperparameter sensitivity"/>
    <div class="fig-cap"><b>图 9：<code>trial_budget</code> 与 <code>interval</code> 参数扫描</b><br><code>trial_budget=6</code> 已触及收益平台期（步数 764.8 &rarr; 753.2）；重规划间隔 <code>5~10</code> 可把 CPU 砍半且质量稳定。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{v91_svg}" alt="V9.1 evolution and BCRD batches"/>
    <div class="fig-cap"><b>图 10：V9.1 混合货架与 <code>bcrd_max_batches</code> 扫描</b><br>静态高积压下 <code>sipp_stream_bcrd</code> 将 <i>F</i> 降至 0.9847；<code>max_batches=1</code> 退化为贪心，<code>&ge;2</code> 即完全释放收益。</div>
  </div>
</div>

<table class="dense">
  <thead>
    <tr>
      <th>实验组别</th>
      <th>调度算法 / 参数点</th>
      <th class="num">平均 Flow (±SD)</th>
      <th class="num">Makespan</th>
      <th class="num">总移动步数</th>
      <th class="num">归一化 F (±SD)</th>
      <th class="num">平均 CPU</th>
    </tr>
  </thead>
  <tbody>
    {_core_rows(("legacy_dynamic_trial_budget", "legacy_dynamic_interval", "v91_dynamic_evolution", "v91_bcrd_max_batches", "v91_static_evolution"))}
  </tbody>
</table>

<div class="callout-good">
  <b>超参数配置与触发机理实证总结（方便队友写“参数消融”章节）</b>：
  <ul>
    <li><b><code>trial_budget = 6</code>（最优默认）</b>：相比 <code>budget=2</code>（总步数 764.8）明显减少绕行拥堵（降至 753.2），而继续增至 <code>10</code> 仅改了 0.01 Flow 却多花 61% CPU（0.452s &rarr; 0.729s）。</li>
    <li><b>重规划周期 <code>interval = 5</code></b>：频率加倍至 <code>2</code> 仅微降 0.09 Flow 但耗时几乎翻倍（1.077s &rarr; 1.862s）；保守选 <code>5</code> 兼顾动态响应与算力。</li>
    <li><b>BCRD 条件触发阈值（<code>min_queue_ratio = 3.0</code>）</b>：动态 V9.1 中 16 任务/4 车在线积压通常低于 <code>3×4=12</code> 阈值，因此 BCRD 自动保持零开销旁路（F=0.9998）；而在静态开局一次性并发 16 任务（&ge;12）时立即介入，只需 <code>max_batches=2</code> 即可获得完整 <b>-1.53%</b> <i>F</i> 收益（<code>m=2/4/6</code> 收敛值一致，推荐设 <code>2~4</code>）。</li>
  </ul>
</div>

<!-- PAGE 7: TEAMMATE PLAYBOOK & COMMANDS -->
<div class="page-break"></div>
<h2>七、队友使用指南：技术报告分工对照表与常用复现命令</h2>

<h3>1. 课程技术报告撰写 —— 代码、结论与图表精确索引</h3>
<table>
  <thead>
    <tr>
      <th style="width:22%;">技术报告章节建议</th>
      <th style="width:38%;">核心论证逻辑（直接可用）</th>
      <th style="width:40%;">对应仓库源码与证据路径</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>系统建模与碰撞约束</b></td>
      <td>离散栅格时空网络、顶点冲突与逆向交换边（swap）检测、V4 同面层序约束、唯一 <code>simulation.py</code> 状态机验解。</td>
      <td><code>src/agv/simulation.py</code>、<code>src/agv/warehouse/</code>、<code>docs/architecture.md</code></td>
    </tr>
    <tr>
      <td><b>核心调度算法设计</b></td>
      <td>（1）SIPP 最大安全区间压缩与增量 <code>VertexReservations</code>；（2）拥堵对 LNS 联合修复；（3）BCRD 影子滚动与静态批最优；<br>（4）WEPA 门控 GA + SIPP 预演。</td>
      <td><code>src/agv/planning/</code>、<code>src/agv/dispatch/</code>、<code>research/recommended-20261024/README.md</code></td>
    </tr>
    <tr>
      <td><b>基础对照与精确差距</b></td>
      <td>Legacy 静/动态跨版本阶梯提升（<code>baseline</code> &rarr; <code>sipp_budget</code>/<code>sipp_batch</code>）；V4 与 V9.1 多层规则适配；小规模精确 Oracle 校验。</td>
      <td><code>results/core-sensitivity-20261121/REPORT.md</code>、<code>results/summary_tables/</code>、<code>src/agv/evaluation/oracle.py</code></td>
    </tr>
    <tr>
      <td><b>多 Seed 与敏感性分析</b></td>
      <td>（1）WEPA 200 次开发集 + 156 次未见验证集对照：<code>gate</code> 稳健最优，<code>gate_preview3</code> 省 44% 算力，揭露 <code>hga</code>/<code>gate_gen24</code> 过拟合与双自适应饱和；<br>（2）主引擎 205 次超参扫描（<code>trial_budget=6</code>, <code>max_batches=2~4</code>）。</td>
      <td><code>results/sensitivity-20261120-v2/</code>、<code>results/sensitivity-20261121-validation/</code>、<code>results/core-sensitivity-20261121/</code>、<code>output/pdf/AGV多seed稳定性与参数敏感性研究.pdf</code></td>
    </tr>
    <tr>
      <td><b>工程可复现与可视化</b></td>
      <td>零第三方依赖核心库、307 项单测、86% 覆盖率、内置 Web 回放前端（<code>agv serve</code>）、独立 CLI 验解。</td>
      <td><code>README.md</code>、<code>src/agv/web/</code>、<code>tests/</code></td>
    </tr>
  </tbody>
</table>

<h3>2. 一键运行、演示答辩与全量复现命令清单</h3>
<pre># 1. 同步最新仓库并安装开发依赖
git pull origin main
uv sync --extra dev     # 或 python3 -m venv .venv &amp;&amp; .venv/bin/pip install -e ".[dev]"

# 2. 课堂答辩 / 本地 Web 可视化回放（支持 Legacy / V4 / V9 / V9.1 实时切换）
.venv/bin/agv serve

# 3. 运行主线 A 代表算法与主线 B WEPA 推荐算法
.venv/bin/agv run --input examples/scenarios/dynamic_medium_burst.json --algorithm sipp_budget --output runs/demo.json
.venv/bin/agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 --algorithm sipp_stream_bcrd --output runs/v91.json
.venv/bin/python research/recommended-20261024/current/run.py --case wepa-day45-bin4335 --seed 0 --output runs/wepa.json

# 4. 工程质检与冻结证据独立校验
make check                                                                 # ruff + format + 307 tests
make coverage                                                              # 覆盖率 86% (门槛 80%)
node --check src/agv/web/static/app.js &amp;&amp; node scripts/check_viewer_contracts.mjs
.venv/bin/python research/recommended-20261024/verification/verify.py      # 114 个指纹与 ZIP CRC 校验
.venv/bin/python scripts/verify_sensitivity_evidence.py verify results/sensitivity-20261120-v2

# 5. 一键重跑补充对比实验与重建本 PDF 报告
.venv/bin/python scripts/run_core_sensitivity.py --output runs/core-check --workers 6
.venv/bin/python scripts/run_wepa_validation_sensitivity.py --output runs/wepa-val-check --workers 6
.venv/bin/python scripts/build_team_summary_pdf.py --overwrite</pre>

<div class="callout-warn" style="margin-top:8px;">
  <b>汇报与写作避坑提示（团队内部约定）</b>：① <b>严禁只挑单个随机种子（best seed）报成绩</b>，统一引用多 seed 均值 ± SD 与同 seed 配对改善率；② <b>严禁直接横向比较不同协议或窗口长度下的绝对 F 分数</b>；③ 所有实验写入 <code>runs/</code> 临时目录，避免污染版本控制下已冻结的 <code>results/</code> 证据包。
</div>

</body>
</html>
"""


def render_pdf(output_path: Path, overwrite: bool = False) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output PDF already exists (pass --overwrite): {output_path}")
    if not CHROME_BIN.is_file():
        raise FileNotFoundError(f"Google Chrome not found at: {CHROME_BIN}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_content = build_html()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        html_file = tmp_path / "team_summary.html"
        html_file.write_text(html_content, encoding="utf-8")

        cmd = [
            str(CHROME_BIN),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output_path}",
            html_file.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not output_path.is_file():
            raise RuntimeError(f"Chrome print-to-pdf failed ({result.returncode}): {result.stderr}")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Chinese project & experiment summary PDF.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination PDF path")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing PDF")
    args = parser.parse_args(argv)
    target = render_pdf(args.output.resolve(), overwrite=args.overwrite)
    print(f"Generated PDF: {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
