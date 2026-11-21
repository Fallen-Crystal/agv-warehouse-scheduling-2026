#!/usr/bin/env python3
"""Build a teammate-friendly Chinese PDF summary of repository organization & experiments.

Reads frozen study summaries and overlap-free figures from:
  - results/wepa-dev-sensitivity-20261120/
  - results/wepa-val-sensitivity-20261121/
  - results/core-sensitivity-20261121/

Renders clean A4 print HTML via Google Chrome headless to:
  results/AGV仓库梳理与实验总结报告.pdf
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
DEFAULT_OUTPUT = ROOT / "results" / "AGV仓库梳理与实验总结报告.pdf"
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

  <!-- Track A -->
  <rect x="8" y="8" width="804" height="128" rx="10" fill="#f3f8fb" stroke="#c8dce6" stroke-width="1.2"/>
  <text x="20" y="29" font-size="12.2" font-weight="700" fill="#173442">主线 A：自研通用调度引擎 (src/agv/) —— 合成 / 分层 / 混合货架 · V4/V9.1 以 baseline 归一化 F</text>

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
  <text x="558" y="73" text-anchor="middle" font-size="9.5" fill="#173442">候选预算 / 静态首轮批规划</text>

  <line x1="636" y1="61" x2="658" y2="61" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="662" y="42" width="136" height="38" rx="6" fill="#ffffff" stroke="#53636c" stroke-width="1.2"/>
  <text x="730" y="59" text-anchor="middle" font-size="10.8" font-weight="700" fill="#173442">sipp_learned</text>
  <text x="730" y="73" text-anchor="middle" font-size="9.5" fill="#53636c">8 特征岭回归排序</text>

  <path d="M 558 80 L 558 92 L 195 92 L 195 98" fill="none" stroke="#21617a" stroke-width="1.3"/>
  <rect x="92" y="96" width="186" height="32" rx="6" fill="#d9eef7" stroke="#173442" stroke-width="1.4"/>
  <text x="185" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V4 分层货架 + bcrd_budget</text>
  <text x="185" y="123" text-anchor="middle" font-size="9" fill="#173442">影子试派多批序列 (F 改善 +3.01%)</text>

  <line x1="278" y1="112" x2="314" y2="112" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="318" y="96" width="174" height="32" rx="6" fill="#ffffff" stroke="#21617a" stroke-width="1.2"/>
  <text x="405" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V9 混合背靠背 + 定位待命</text>
  <text x="405" y="123" text-anchor="middle" font-size="9" fill="#53636c">安全待命点 + 动态定位</text>

  <line x1="492" y1="112" x2="524" y2="112" stroke="#21617a" stroke-width="1.5" marker-end="url(#arrA)"/>

  <rect x="528" y="96" width="270" height="32" rx="6" fill="#e6f2f7" stroke="#21617a" stroke-width="1.4"/>
  <text x="663" y="110" text-anchor="middle" font-size="10.3" font-weight="700" fill="#173442">V9.1 流式关闭 + BCRD 尾保护</text>
  <text x="663" y="123" text-anchor="middle" font-size="9" fill="#173442">静态场景 max_batches=2 改善 +1.53%</text>

  <!-- Track B -->
  <rect x="8" y="144" width="804" height="126" rx="10" fill="#f3faf6" stroke="#c3e0d1" stroke-width="1.2"/>
  <text x="20" y="165" font-size="12.2" font-weight="700" fill="#16402e">主线 B：WEPAStacks 真实订单流 (research/) —— 62×47 网格 / 6 车 / 5 层 / 900s 窗口 · 线性目标 F</text>

  <rect x="20" y="178" width="110" height="38" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="75" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#16402e">fcfs / eta</text>
  <text x="75" y="209" text-anchor="middle" font-size="9.5" fill="#53636c">规则基线 (0.5~0.6s)</text>

  <line x1="130" y1="197" x2="152" y2="197" stroke="#297b58" stroke-width="1.5" marker-end="url(#arrB)"/>

  <rect x="156" y="178" width="128" height="38" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="220" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#16402e">simple → wide</text>
  <text x="220" y="209" text-anchor="middle" font-size="9.5" fill="#53636c">早期 GA → 扩预算 GA</text>

  <line x1="284" y1="197" x2="306" y2="197" stroke="#297b58" stroke-width="1.5" marker-end="url(#arrB)"/>

  <rect x="310" y="178" width="176" height="38" rx="6" fill="#dcf2e7" stroke="#16402e" stroke-width="1.8"/>
  <text x="398" y="195" text-anchor="middle" font-size="11" font-weight="700" fill="#16402e">gate (保留默认方案)</text>
  <text x="398" y="209" text-anchor="middle" font-size="9.5" fill="#16402e">事件门控 (-63% 搜索) + SIPP</text>

  <line x1="486" y1="197" x2="510" y2="197" stroke="#9a5b13" stroke-width="1.5" marker-end="url(#arrWarn)"/>

  <rect x="514" y="178" width="150" height="38" rx="6" fill="#fff8eb" stroke="#c8832c" stroke-width="1.3"/>
  <text x="589" y="195" text-anchor="middle" font-size="10.8" font-weight="700" fill="#7a4508">hungarian → hga</text>
  <text x="589" y="209" text-anchor="middle" font-size="9.2" fill="#9a5b13">开发 +0.95% / 验证 -1.12%</text>

  <line x1="486" y1="205" x2="510" y2="239" stroke="#297b58" stroke-width="1.4" marker-end="url(#arrB)"/>

  <rect x="20" y="226" width="236" height="34" rx="6" fill="#ffffff" stroke="#297b58" stroke-width="1.2"/>
  <text x="138" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#16402e">gate_preview3 (算力受限选项)</text>
  <text x="138" y="254" text-anchor="middle" font-size="9" fill="#297b58">CPU 降约 44%~46%，F 差 -0.33%~-0.68%</text>

  <rect x="272" y="226" width="218" height="34" rx="6" fill="#f8fafc" stroke="#64748b" stroke-width="1.2"/>
  <text x="381" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#334155">dqn-experiment-v2 (已归档)</text>
  <text x="381" y="254" text-anchor="middle" font-size="9" fill="#64748b">相对纯自适应 GA -0.37%，未采用</text>

  <rect x="506" y="226" width="292" height="34" rx="6" fill="#f0f7f4" stroke="#297b58" stroke-width="1.2"/>
  <text x="652" y="241" text-anchor="middle" font-size="10.3" font-weight="700" fill="#16402e">hga_adapt01 (既有验证窗组合对照)</text>
  <text x="652" y="254" text-anchor="middle" font-size="9" fill="#16402e">比 hga +0.79% (3/0/1)，仍比 gate -0.28%</text>
</svg>"""


def build_html() -> str:
    dev_dir = ROOT / "results" / "wepa-dev-sensitivity-20261120"
    val_dir = ROOT / "results" / "wepa-val-sensitivity-20261121"
    core_dir = ROOT / "results" / "core-sensitivity-20261121"

    dev_summary = {row["variant"]: row for row in _load_csv(dev_dir / "summary.csv")}
    val_data = _load_json(val_dir / "summary.json")
    val_summary = {row["variant"]: row for row in val_data["summary"]}
    val_paired = {f"{r['candidate']}_vs_{r['baseline']}": r for r in val_data["paired"]}

    core_data = _load_json(core_dir / "summary.json")
    core_rows = core_data["summary"]
    core_paired = {(r["group"], r["candidate"]): r for r in core_data.get("paired", [])}

    dev_paired_map = {
        "wide_vs_simple": "+0.988% (3/1/0)",
        "gate_vs_wide": "+0.112% (1/3/0)",
        "hga_vs_gate": "+0.946% (2/1/1)",
        "hungarian_vs_gate": "-1.285% (0/1/3)",
        "gate_vs_eta": "+2.753% (3/0/1)",
        "gate_vs_fcfs": "+4.301% (3/0/1)",
        "gate_preview3_vs_gate": "-0.683% (0/2/2)",
        "gate_gen8_vs_gate": "-1.041% (1/1/2)",
        "gate_gen24_vs_gate": "未测",
        "wide_adapt01_vs_wide_adapt00": "+0.938% (3/1/0)",
        "wide_adapt11_vs_wide_adapt00": "+0.234% (2/0/2)",
        "hga_adapt01_vs_hga": "未测",
    }

    wepa_compare_specs = [
        ("fcfs", "先到先服务规则", "gate_vs_fcfs"),
        ("eta", "最早到达局部估算", "gate_vs_eta"),
        ("hungarian", "匈牙利局部匹配", "hungarian_vs_gate"),
        ("simple", "早期 GA 基线", "wide_vs_simple"),
        ("wide", "扩预算联合 GA", "wide_vs_simple"),
        ("gate", "保留默认：门控+SIPP", "gate_vs_wide"),
        ("hga", "匈牙利初始化 GA", "hga_vs_gate"),
        ("gate_preview3", "预演次数=3 (降耗)", "gate_preview3_vs_gate"),
        ("gate_gen8", "演化代数=8 (减半)", "gate_gen8_vs_gate"),
        ("gate_gen24", "演化代数=24 (扩预算)", "gate_gen24_vs_gate"),
        ("wide_adapt00", "移植 GA 无自适应", None),
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
            "legacy_static_evolution": "Legacy 静态 (6车24单)",
            "legacy_dynamic_evolution": "Legacy 动态 (6车24单)",
            "legacy_dynamic_trial_budget": "参数: trial_budget",
            "legacy_dynamic_interval": "参数: interval",
            "v4_dynamic_evolution": "V4 分层动态 (3层18单)",
            "v91_dynamic_evolution": "V9.1 混合动态 (5层16单)",
            "v91_bcrd_max_batches": "参数: max_batches",
            "v91_static_evolution": "V9.1 混合静态 (5层16单)",
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
            p = core_paired.get((row["group"], row["variant"]))
            p_str = (
                f"{p['mean_improve_pct']:+.2f}% ({p['wins']}/{p['ties']}/{p['losses']})"
                if p
                else "-"
            )
            hl = ""
            if row["variant"] in ("sipp_batch", "bcrd_budget", "sipp_stream_bcrd", "v91_bcrd_m2"):
                hl = ' class="hl-good"'
            out.append(
                f"<tr{hl}>"
                f"<td>{html.escape(glabel)}</td>"
                f"<td><code>{html.escape(row['variant'])}</code></td>"
                f"<td class='num'>{row['mean_flow_time']:.2f} (±{row['flow_sd']:.2f})</td>"
                f"<td class='num'>{row['makespan']:.2f}</td>"
                f"<td class='num'>{row['moves']:.1f}</td>"
                f"<td class='num'>{html.escape(wscore)}</td>"
                f"<td class='num'>{html.escape(p_str)}</td>"
                f"<td class='num'>{row['cpu_seconds']:.3f}s</td>"
                "</tr>"
            )
        return "\n".join(out)

    val_evol_svg = _svg_data_uri(val_dir / "figures" / "validation_evolution.svg")
    val_param_svg = _svg_data_uri(val_dir / "figures" / "validation_budget_and_adaptive.svg")
    legacy_static_svg = _svg_data_uri(core_dir / "figures" / "legacy_static_flow.svg")
    legacy_dyn_svg = _svg_data_uri(core_dir / "figures" / "legacy_dynamic_flow.svg")
    legacy_hp_svg = _svg_data_uri(core_dir / "figures" / "legacy_hyperparam_sensitivity.svg")
    v91_svg = _svg_data_uri(core_dir / "figures" / "v91_evolution_and_bcrd_batches.svg")

    pareto_png = _png_data_uri(dev_dir / "figures" / "pareto.png")
    paired_png = _png_data_uri(dev_dir / "figures" / "paired_effects.png")
    budget_2x2_png = _png_data_uri(dev_dir / "figures" / "budget_2x2.png")
    adapt_2x2_png = _png_data_uri(dev_dir / "figures" / "adaptive_2x2.png")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>AGV 仓库梳理与实验总结报告</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 13mm 13mm 14mm 13mm;
    @bottom-left {{
      content: "agv-warehouse-scheduling-2026 · 仓库整理与多 Seed 实验梳理报告 (2026-11-21)";
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
    font-size: 9.2pt;
    line-height: 1.48;
  }}
  .hero {{
    background: linear-gradient(135deg, #123142 0%, #1d5773 100%);
    color: #ffffff;
    border-radius: 10px;
    padding: 15px 19px;
    margin-bottom: 11px;
  }}
  .hero .kicker {{
    font-size: 8pt;
    letter-spacing: 0.06em;
    color: #b7dce9;
    margin-bottom: 4px;
  }}
  .hero h1 {{
    margin: 0 0 5px 0;
    font-size: 17pt;
    line-height: 1.25;
  }}
  .hero p {{
    margin: 0;
    font-size: 8.8pt;
    color: #e3f1f7;
  }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 11px;
  }}
  .kpi-card {{
    background: #f3f8fb;
    border: 1px solid #d1e2eb;
    border-top: 3px solid #21617a;
    border-radius: 7px;
    padding: 7px 9px;
  }}
  .kpi-card .val {{
    font-size: 13.5pt;
    font-weight: 700;
    color: #123142;
    line-height: 1.2;
  }}
  .kpi-card .lbl {{
    font-size: 7.7pt;
    color: #53636c;
    margin-top: 2px;
  }}
  h2 {{
    font-size: 12pt;
    color: #123142;
    border-left: 4px solid #21617a;
    padding-left: 8px;
    margin: 11px 0 6px 0;
    break-after: avoid;
  }}
  h3 {{
    font-size: 10pt;
    color: #1d5773;
    margin: 8px 0 4px 0;
    break-after: avoid;
  }}
  p {{
    margin: 0 0 5px 0;
  }}
  ul, ol {{
    margin: 3px 0 6px 0;
    padding-left: 17px;
  }}
  li {{
    margin-bottom: 2.5px;
  }}
  code {{
    font-family: "SFMono-Regular", Menlo, Consolas, monospace;
    font-size: 8pt;
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
    padding: 7px 10px;
    margin: 6px 0;
    break-inside: avoid;
  }}
  .callout-warn {{
    background: #fff9ef;
    border: 1px solid #ecd5ab;
    border-left: 4px solid #b46914;
    border-radius: 6px;
    padding: 7px 10px;
    margin: 6px 0;
    break-inside: avoid;
  }}
  .callout-good {{
    background: #f2faf6;
    border: 1px solid #c3e2d2;
    border-left: 4px solid #297b58;
    border-radius: 6px;
    padding: 7px 10px;
    margin: 6px 0;
    break-inside: avoid;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 5px 0 8px 0;
    font-size: 7.7pt;
    break-inside: avoid;
  }}
  th {{
    background: #1a475e;
    color: #ffffff;
    text-align: left;
    padding: 4.5px 5.5px;
    font-weight: 600;
    border: 1px solid #1a475e;
  }}
  th.num, td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  td {{
    padding: 3.5px 5.5px;
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
    font-size: 7.2pt;
    margin: 4px 0 6px 0;
  }}
  table.dense th {{
    padding: 3.2px 4.5px;
  }}
  table.dense td {{
    padding: 2.0px 4.5px;
    line-height: 1.22;
  }}
  table.dense td.num, table.dense th.num {{
    white-space: nowrap;
  }}
  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 9px;
    margin: 5px 0;
    break-inside: avoid;
  }}
  .fig-card {{
    border: 1px solid #d5e1e8;
    border-radius: 7px;
    padding: 6px 7px 4px 7px;
    background: #ffffff;
    break-inside: avoid;
    margin-bottom: 6px;
  }}
  .fig-card img {{
    width: 100%;
    height: auto;
    display: block;
  }}
  .fig-cap {{
    font-size: 7.6pt;
    color: #53636c;
    margin-top: 3.5px;
    line-height: 1.32;
  }}
  .page-break {{
    page-break-before: always;
    break-before: page;
  }}
  pre {{
    margin: 4px 0 7px 0;
    background: #f4f7f9;
    border: 1px solid #d8e2e8;
    border-radius: 6px;
    padding: 6px 8px;
    font-family: "SFMono-Regular", Menlo, Consolas, monospace;
    font-size: 7.5pt;
    line-height: 1.4;
    white-space: pre-wrap;
    break-inside: avoid;
  }}
</style>
</head>
<body>

<!-- PAGE 1: TASK COMPLETION & REPO AUDIT -->
<div class="hero">
  <div class="kicker">2026 人工智能大作业 · 仓库穿梭无人车（AGV）智能调度 · 审查整改与实验梳理报告</div>
  <h1>AGV 仓库结构整理、文档纠偏、图表修复与实验脉络总结</h1>
  <p>面向后续大作业实验文档撰写 ｜ 依据《AGV 仓库文档审查与改写稿》完成 P0/P1/P2 全部整改与 561 次实验口径统一</p>
</div>

<div class="kpi-grid">
  <div class="kpi-card">
    <div class="val">561 次</div>
    <div class="lbl">多 Seed / 超参有效运行<br>(200 开发 + 156 验证 + 205 主引擎)</div>
  </div>
  <div class="kpi-card">
    <div class="val">100% 验解</div>
    <div class="lbl">全部轨迹通过独立物理校验<br>(碰撞 / 换边 / 层序零违例)</div>
  </div>
  <div class="kpi-card">
    <div class="val">3 套统一</div>
    <div class="lbl">目录统一 <code>results/&lt;ID&gt;/REPORT.md</code><br>删除顶层 <code>output/</code> 并建总索引</div>
  </div>
  <div class="kpi-card">
    <div class="val">0 图表重叠</div>
    <div class="lbl">修复 Pareto 标签重叠、2×2 对比度<br>与 6 张 SVG 误差线遮挡数值问题</div>
  </div>
</div>

<h2>一、本轮任务完成清单（依据审查改写稿逐项落实）</h2>

<table class="dense">
  <thead>
    <tr>
      <th style="width:17%;">整改维度</th>
      <th style="width:39%;">原仓库存在的问题</th>
      <th style="width:44%;">已完成修改与落盘位置</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>逻辑纠偏 (P0)</b></td>
      <td>将 10 月已选型窗口误称“未见验证”；误用“显著”“稳健最优”“上界”“过拟合”“性能阶梯”；<code>gate</code> 单 seed 与 3-seed F 未解释；推荐包 README 源码路径前后矛盾。</td>
      <td>全部改称<b>“既有验证窗口（回顾性复评）”</b>；删除无依据程度副词；明确 <code>gate</code> 0.896406（seed 0）与 0.899159（seed 0–2）不矛盾；改写推荐包 <code>README.md</code> 并拆出 <code>CHANGELOG.md</code>、更新 <code>MANIFEST.sha256.json</code>（115/115 校验通过）。</td>
    </tr>
    <tr>
      <td><b>表述统一 (P1)</b></td>
      <td>改善率正负号混用；报告缺少首屏结论与配对区间/配对表；开发集正文夹杂 56 行明细与 60 行重评分；命令混用 <code>agv</code>/<code>.venv/bin</code>。</td>
      <td>全仓统一<b>“改善率正数 = 目标降低 = 更好”</b>与 <code>T/R/D</code> 定义；3 份报告统一为<b>「结论 → 方法 → 局限」</b>结构；补齐验证集 bootstrap 95% 区间与主引擎 5-seed 配对表；开发集明细移至 <code>appendix.md</code>、重评分压缩为前 5 名矩阵；命令统一 <code>uv run</code> 并增设 <code>docs/usage.md</code>。</td>
    </tr>
    <tr>
      <td><b>结构整理 (P2)</b></td>
      <td>报告分散于 <code>results/*/REPORT.md</code>、<code>report/中文实验报告.md</code>、<code>output/pdf/</code> 五处；目录命名不统一；历史结果无索引。</td>
      <td>统一为 <code>results/wepa-dev-sensitivity-20261120/</code>、<code>results/wepa-val-sensitivity-20261121/</code>、<code>results/core-sensitivity-20261121/</code>（均为 <code>REPORT.md + figures/</code>）；PDF 迁入 <code>results/</code> 并删除顶层 <code>output/</code>；新增总索引 <code>results/README.md</code>。</td>
    </tr>
    <tr>
      <td><b>图表修复</b></td>
      <td><code>pareto.png</code> 右下角 6 个标签严重重叠；<code>budget_2x2</code> / <code>adaptive_2x2</code> 深蓝底黑字难以辨认；6 张 SVG 柱顶数值与误差线重叠且 2 张含未转义 <code>&amp;</code>。</td>
      <td>重写 <code>report_sensitivity_study.py</code> Pareto 避让引线与热图自适应黑白字色；重写两套 SVG 生成器将数值置于误差线顶端之上并做 XML 转义；全部图件已重绘并逐张目视核验。</td>
    </tr>
  </tbody>
</table>

<h3>整理后的核心目录与资产导航（供队友直接检索）</h3>
<table class="dense">
  <thead>
    <tr>
      <th style="width:30%;">路径</th>
      <th style="width:70%;">内容与定位（均为 <code>main</code> 分支现行结构 v0.6.0）</th>
    </tr>
  </thead>
  <tbody>
    <tr><td><code>README.md</code> &amp; <code>docs/usage.md</code></td><td>项目精简总览（快速开始 → 双主线 → 方案速查 → 结论摘要 → 实验索引）与完整 CLI/复现命令。</td></tr>
    <tr><td><code>src/agv/</code></td><td>主线 A 自研通用引擎（零三方依赖）：<code>planning/</code>、<code>dispatch/</code>、<code>simulation.py</code>、<code>evaluation/</code>、<code>web/</code>。</td></tr>
    <tr><td><code>research/recommended-20261024/</code></td><td>主线 B WEPA 推荐交付包（实际运行源码 <code>current/code-guide/improved</code>，ZIP 作冻结审计）；含 <code>CHANGELOG.md</code>。</td></tr>
    <tr><td><code>research/dqn-experiment-v2/</code></td><td>已归档 DQN 双动作选择实验包（5 测试日相对纯自适应 GA −0.37%，未超越纯自适应 GA）。</td></tr>
    <tr><td><code>results/wepa-dev-sensitivity-20261120/</code></td><td>主线 B 开发窗 200 次冻结证据：<code>REPORT.md</code>、<code>appendix.md</code>、<code>figures/</code>（已去重叠）及原 9 页 PDF。</td></tr>
    <tr><td><code>results/wepa-val-sensitivity-20261121/</code></td><td>主线 B 既有验证窗 156 次回顾性复评：<code>REPORT.md</code>（含 bootstrap 95% 区间）、<code>paired.csv</code>、<code>figures/</code>。</td></tr>
    <tr><td><code>results/core-sensitivity-20261121/</code></td><td>主线 A 核心引擎 205 次 5-seed 演进与超参扫描：<code>REPORT.md</code>（含 5-seed 配对表）、<code>figures/</code>。</td></tr>
    <tr><td><code>results/README.md</code></td><td>全量现行实验 + 历史目录（<code>v1/v2/v4/v9/v91/bcrd</code> 等）+ 22 份 <code>summary_tables/</code> CSV 逐表索引。</td></tr>
  </tbody>
</table>

<div class="callout">
  <b>Git 与环境核查说明</b>：此前 Codex 提交分支 <code>origin/codex/multiseed-sensitivity-20261120</code> 已 Fast-forward 合入 <code>main</code>；GitHub 此前显示的 <code>✕ 0 / 8</code> 系账号账单锁导致 Actions Runner 未启动，并非代码或测试失败（本机 <code>make check</code> 全部测试与证据校验均已通过）。
</div>

<!-- PAGE 2: DUAL-TRACK EVOLUTION -->
<div class="page-break"></div>
<h2>二、项目研究脉络全景：两条主线与口径边界</h2>
<p>整座仓库围绕<b>“多取货任务并发下的无碰撞路径规划 + 多车任务指派”</b>沿两条互补主线推进。写实验文档时务必先声明各自的目标函数与比较边界，避免混排不同协议的绝对 <i>F</i> 值：</p>

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
      <td><b>场景与入口</b></td>
      <td>合成栅格（Legacy）、V4 多层单面货架、V9/V9.1 混合背靠背货架；通过 <code>uv run agv</code> 统一运行。</td>
      <td>62×47 网格、6 车、5 层、900 秒窗口（货位映射种子 17）；通过 <code>research/recommended-20261024/current/run.py</code> 运行。</td>
    </tr>
    <tr>
      <td><b>核心演进链</b></td>
      <td><code>baseline</code> &rarr; <code>joint_only/batch</code> &rarr; <code>sipp_conflict/budget/batch</code> &rarr; <code>bcrd_budget</code> &rarr; <code>v9.1</code>。</td>
      <td><code>fcfs</code> / <code>eta</code> &rarr; <code>simple</code> &rarr; <code>wide</code> &rarr; <b><code>gate</code></b>（默认）&rarr; <code>hga</code> / 预算与自适应消融。</td>
    </tr>
    <tr>
      <td><b>目标函数 F</b></td>
      <td><b>V4/V9.1</b>：<code>F = 0.5*(T/T_ref) + 0.3*(R/R_ref) + 0.2*(D/D_ref)</code>（以同场景 <code>baseline</code> 为 1.0）；Legacy 无固定参照，不计 <i>F</i>。</td>
      <td>独立固定尺度线性目标（越低越好）：<br><code>F = 0.5*(T/900) + 0.3*(R/900) + 0.2*(D/5400)</code>（<i>T</i> 不含最终返库，<i>D</i> 含最终返库）。</td>
    </tr>
    <tr>
      <td><b>统一符号约定</b></td>
      <td colspan="2"><b>T</b> = 完工时间（Makespan / 最后一单完成时刻）；<b>R</b> = 平均流程/响应时间（Flow Time / Response）；<b>D</b> = 总移动步数/里程。<b>改善率正数 = 候选目标值低于基线 = 更好</b>。不同协议与窗口长度的绝对 <i>F</i> 不可直接横比。</td>
    </tr>
  </tbody>
</table>

<div class="callout-good">
  <b>关键逻辑串联（写实验报告总述可直接复用）</b>：主线 A 验证底层离散时空规划器（A* &rarr; SIPP 安全区间 &rarr; LNS 拥堵修复 &rarr; BCRD 影子批试派）在合成与多层物理规则下的正确性与收益边界；主线 B 固定底层 SIPP 验解环境，在大规模真实 WEPA 订单流上系统比较规则启发式、遗传算法预算控制、事件门控与自适应算子的多 seed 表现。
</div>

<!-- PAGE 3: WEPA DEV VS EXISTING VAL -->
<div class="page-break"></div>
<h2>三、主线 B（WEPA）：开发窗口（200 次）vs 既有验证窗口复评（156 次）</h2>
<p>开发窗口（<code>day12/32/33/45</code>，201 条请求）与既有验证窗口（<code>day40/61/83/87</code>，199 条请求，2026-10 已用于选定 <code>gate</code>，本轮为<b>回顾性复评</b>）均按来源日期等权汇总、同窗口同 seed 严格配对。以下两张 SVG 已修复数值与误差线重叠问题：</p>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{val_evol_svg}" alt="WEPA Validation Evolution"/>
    <div class="fig-cap"><b>图 1（既有验证窗口 7 方案演进）</b>：在 4 个验证窗上，<code>wide</code>（0.8983）与 <code>gate</code>（0.8992）在全部日期优于 <code>fcfs</code>/<code>eta</code>/<code>hungarian</code>；开发集最优的 <code>hga</code> 在此 4 窗全负。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{val_param_svg}" alt="WEPA Validation Hyperparameters"/>
    <div class="fig-cap"><b>图 2（既有验证窗口预算与自适应对照）</b>：<code>gate_preview3</code> 降耗约 44% 且 F 仅差 −0.33%；扩大至 24 代（<code>gate_gen24</code>）反而最差（−1.41%）；<code>hga_adapt01</code> 获最低 seed SD（0.00521）。</div>
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

<div class="callout-warn">
  <b>主线 B 实证结论（严格限定在数据支持范围内，无过度宣称）</b>：
  <ul>
    <li><b>GA 稳定优于规则基线</b>：在 4 个既有验证窗口上，<code>gate</code> 相对 <code>fcfs</code> 改善 <b>+5.45%</b>、相对 <code>eta</code> <b>+2.43%</b>、相对 <code>hungarian</code> <b>+3.87%</b>，4 个日期全部改善（4/0/0）。</li>
    <li><b>为何保留 <code>gate</code> 而非改用 <code>wide</code> 或 <code>hga</code></b>：<code>gate</code> 与 <code>wide</code> 无可分辨差异（验证 −0.10% 0/2/2，开发 +0.11% 1/3/0），但 <code>gate</code> 在开发集将 GA 触发次数减少 <b>63%</b>（205 vs 560 次）并延续 2026-10 推荐口径（10 月 <code>gate</code> 为单 seed 0 均值 0.896406，本轮为 seed 0–2 均值 0.899159，不矛盾）；开发集最优的 <code>hga</code>（+0.95%）在既有验证窗口 4 日全负（−1.12%，0/0/4），因此不采用。</li>
    <li><b>预算与自适应算子规律</b>：将代数扩大至 24 代（<code>gate_gen24</code>）比默认差 −1.41%（0/0/4），说明默认代数不是性能瓶颈；<code>gate_preview3</code> 缩短完整预演至 3 次，CPU 降低约 <b>44%–46%</b> 而 F 仅差 −0.33%（验证）至 −0.68%（开发），适合算力受限档。仅开交叉自适应（<code>wide_adapt01</code>）在开发集 +0.94%（3/1/0）、验证集 −0.54%（1/0/3），跨集不稳定；开发集开启变异自适应时超 <b>86%</b> 代数触及 0.95 上限（<code>wide_adapt10</code> 4,639/5,376 代、<code>wide_adapt11</code> 4,640/5,360 代）。</li>
  </ul>
</div>

<!-- PAGE 4: WEPA DEV KEY CHARTS (FIXED!) -->
<div class="page-break"></div>
<h2>四、主线 B 开发窗口冻结对照图（已修复标签重叠与热图对比度）</h2>
<p>以下四张图表均由更新后的 <code>scripts/report_sensitivity_study.py</code> 从冻结 <code>aggregate.json</code> 重绘，已彻底消除原 <code>pareto.png</code> 右下角标签重叠及 2×2 热图深底黑字问题，可直接放进实验报告对应小节：</p>

<div class="two-col">
  <div class="fig-card">
    <img src="{pareto_png}" alt="Pareto frontier"/>
    <div class="fig-cap"><b>图 3：质量与算力 Pareto 视图（共同 Seed [0,1]，已去重叠）</b><br>虚线连接非支配前沿（<code>fcfs/eta/hungarian &rarr; gate_preview3 &rarr; hga</code>）；右侧密集簇通过引线清晰分隔全部 15 个方案。</div>
  </div>
  <div class="fig-card">
    <img src="{paired_png}" alt="Paired effects"/>
    <div class="fig-cap"><b>图 4：开发集 14 项配对改善率与日期 bootstrap 95% 区间</b><br>严格按同窗口、同 seed 配对；仅 4 个来源日期，区间作描述性展示，不做统计显著性推断。</div>
  </div>
</div>

<div class="two-col">
  <div class="fig-card">
    <img src="{budget_2x2_png}" alt="Budget 2x2"/>
    <div class="fig-cap"><b>图 5：代理预算 × 完整预演（<code>proxy × preview</code>）2×2 交互</b><br>已修复深色格自动反白字体；直观呈现将 <code>preview</code> 从 6 降至 3 可使 CPU 减半（13.98 &rarr; 7.65s）。</div>
  </div>
  <div class="fig-card">
    <img src="{adapt_2x2_png}" alt="Adaptive 2x2"/>
    <div class="fig-cap"><b>图 6：自适应变异 × 交叉（<code>pm × pc</code>）2×2 因子分解</b><br>开发集上 <code>wide_adapt01</code>（仅交叉开）表现最好，但在既有验证窗未复现，提示写作时须成对呈现两集结果。</div>
  </div>
</div>

<div class="callout">
  <b>开发集权重重评分稳健性（4 组权重 × 前 5 名排名，共同 seed [0,1]）</b>：在默认（0.5/0.3/0.2）、偏完工（0.6/0.2/0.2）、偏响应（0.4/0.4/0.2）、偏里程（0.4/0.2/0.4）4 组权重下，同一批轨迹重新计分的前 5 名集合完全不变——第 1 名始终为 <code>hga</code>，第 2–4 名均为 <code>gate</code> / <code>wide</code> / <code>wide_adapt01</code>，第 5 名始终为 <code>wide_adapt00</code>。
</div>

<!-- PAGE 5: CORE ENGINE EVOLUTION -->
<div class="page-break"></div>
<h2>五、主线 A（<code>src/agv/</code>）跨版本演进对比（205 次 / 5 Seeds）</h2>
<p>为补全主仓库从早期 <code>baseline</code> 到最新 <code>v9.1</code> 的演进证据，<code>scripts/run_core_sensitivity.py</code> 在 <code>seeds=[0..4]</code> 下执行 41 组配置共 205 次运行（205/205 通过 <code>validate()</code>），并已补充<b>同 seed 配对改善表</b>与无遮挡 SVG 图：</p>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_static_svg}" alt="Legacy static evolution"/>
    <div class="fig-cap"><b>图 7：Legacy 静态场景演进（6 车 24 单，数值已置于误差线之上）</b><br><code>sipp_batch</code> 相对 <code>baseline</code> 将平均流程时间 R 改善 +2.62%（50.82 &rarr; 49.49），总步数 D 减少 4.24%。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_dyn_svg}" alt="Legacy dynamic evolution"/>
    <div class="fig-cap"><b>图 8：Legacy 动态到达演进（6 车 24 单）</b><br>同 seed 配对下各改进方案均 5/0/0 优于 <code>baseline</code>（约 +3.4%），但各 SIPP 变体间差异小于 0.15。</div>
  </div>
</div>

<table class="dense">
  <thead>
    <tr>
      <th>实验组别</th>
      <th>调度算法</th>
      <th class="num">R 平均流程 (±SD)</th>
      <th class="num">T 完工时间</th>
      <th class="num">D 总步数</th>
      <th class="num">归一化 F (±SD)</th>
      <th class="num">同 seed 配对改善</th>
      <th class="num">平均 CPU</th>
    </tr>
  </thead>
  <tbody>
    {_core_rows(("legacy_static_evolution", "legacy_dynamic_evolution", "v4_dynamic_evolution"))}
  </tbody>
</table>

<div class="callout">
  <b>Legacy 与 V4 客观结论（对照 5-seed 同种子配对与标准差）</b>：
  <ul>
    <li><b>V4 动态（推荐 <code>bcrd_budget</code>）</b>：<code>bcrd_budget</code> 相对 <code>baseline</code> 将归一化 F 改善 <b>+3.01%</b>（4 胜 1 平 0 负，完工时间 139.6 &rarr; 132.8，CPU 仅 0.173s）；同组 <code>sipp_budget</code> 与 <code>sipp_matching</code> 均值改善不足 0.6%，落于标准差内。</li>
    <li><b>Legacy 静态（<code>sipp_batch</code> 换算力）</b>：<code>sipp_batch</code> 将 R 改善 +2.63%（5/0/0）、D 降至全场最低 596.4，但 CPU 约为 <code>baseline</code> 的 130 倍（0.078s &rarr; 10.270s），明显快于同精度的 <code>joint_batch</code>（14.152s）。</li>
    <li><b>Legacy 动态（收益集中于“相对 baseline”）</b>：各改进方案平均 R 约 27.8（同 seed 均 5/0/0 优于 <code>baseline</code> 28.84），但 5 个随机场景间跨 seed SD 达 ±3，且不同 SIPP 变体之间无可分辨差异。注：Legacy 无固定参照基线，表中 F 记为 <code>-</code>。</li>
  </ul>
</div>

<!-- PAGE 6: CORE ENGINE HYPERPARAMS & V9.1 -->
<div class="page-break"></div>
<h2>六、主线 A 超参数敏感性与 V9.1 混合货架分析</h2>

<div class="two-col">
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{legacy_hp_svg}" alt="Legacy hyperparameter sensitivity"/>
    <div class="fig-cap"><b>图 9：<code>trial_budget</code>（2/4/6/10）与 <code>interval</code>（2/5/10）扫描</b><br>两项参数在所测区间内对 R 的影响均小于 0.15 步，<code>b2</code>（0.284s）与 <code>int10</code>（0.401s）算力最省。</div>
  </div>
  <div class="fig-card" style="margin-bottom:5px;padding:5px 6px;">
    <img src="{v91_svg}" alt="V9.1 evolution and BCRD batches"/>
    <div class="fig-cap"><b>图 10：V9.1 静态场景与 <code>max_batches</code>（纵轴已缩放至 0.94–1.04）</b><br><code>max_batches</code> 由 1 增至 2 使 F 改善约 +1.53%，增至 4/6 结果完全一致；数值与误差线无遮挡。</div>
  </div>
</div>

<table class="dense">
  <thead>
    <tr>
      <th>实验组别</th>
      <th>调度算法 / 参数点</th>
      <th class="num">R 平均流程 (±SD)</th>
      <th class="num">T 完工时间</th>
      <th class="num">D 总步数</th>
      <th class="num">归一化 F (±SD)</th>
      <th class="num">同 seed 配对改善</th>
      <th class="num">平均 CPU</th>
    </tr>
  </thead>
  <tbody>
    {_core_rows(("legacy_dynamic_trial_budget", "legacy_dynamic_interval", "v91_dynamic_evolution", "v91_bcrd_max_batches", "v91_static_evolution"))}
  </tbody>
</table>

<div class="callout-good">
  <b>主线 A 参数与 V9.1 实证要点（已修正原版过度解读）</b>：
  <ul>
    <li><b><code>trial_budget</code> 与 <code>interval</code></b>：在 2–10 范围内对平均流程时间几乎无影响（<code>b2</code> 27.86、T 138.60、CPU 0.284s；<code>b6</code> 27.82、T 139.00、CPU 0.452s），算力敏感场景可直接取 <code>b2</code> 与 <code>interval=10</code>。</li>
    <li><b>V9.1 动态场景（无差异边界）</b>：除 <code>sipp_stream_matching</code>（F 均值 0.9935，3 胜 2 负波动大）外，其余 4 种流式/BCRD 方案的 R、T 与 <code>baseline</code> 完全一致（134.16 / 330.20），说明该动态负载下队列未触及 BCRD 触发阈值，改进未生效。</li>
    <li><b>V9.1 静态场景（<code>max_batches=2</code> 即饱和）</b>：静态并发下 <code>sipp_stream_matching</code>（+1.55%，5/0/0）与 <code>sipp_stream_bcrd</code>（+1.53%，4/1/0）稳定降低 F；<code>max_batches</code> 从 1 升到 2 获得全部收益，2/4/6 数值完全相同，建议直接取 <code>2</code>。</li>
  </ul>
</div>

<!-- PAGE 7: REPORT WRITING GUIDE & COMMANDS -->
<div class="page-break"></div>
<h2>七、后续大作业实验文档撰写逻辑与复现命令清单</h2>

<h3>1. 推荐实验文档章节结构与仓库证据映射</h3>
<table>
  <thead>
    <tr>
      <th style="width:21%;">实验文档章节</th>
      <th style="width:41%;">建议写作逻辑（紧扣事实、不夸大）</th>
      <th style="width:38%;">直接引用的源码、数据与图表</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>1. 问题建模与验解约束</b></td>
      <td>离散栅格时空网络、顶点/换边冲突、V4/V9.1 分层层序规则、唯一状态机独立验解；先声明主线 A/B 两套 <i>F</i> 口径及“正数=改善”约定。</td>
      <td><code>src/agv/simulation.py</code>、<code>src/agv/warehouse/</code>、<code>docs/architecture.md</code>、<code>research/recommended-20261024/README.md</code></td>
    </tr>
    <tr>
      <td><b>2. 调度与规划算法</b></td>
      <td>主线 A：时空 A* &rarr; SIPP 安全区间 &rarr; LNS 拥堵修复 &rarr; BCRD 影子批试派；主线 B：规则基线 &rarr; 联合 GA &rarr; 门控 GA+SIPP（<code>gate</code>）及算子消融。</td>
      <td><code>src/agv/planning/</code>、<code>src/agv/dispatch/</code>、<code>research/recommended-20261024/docs/算法主线与接口.md</code></td>
    </tr>
    <tr>
      <td><b>3. 主线 A 演进与消融</b></td>
      <td>诚实呈现收益边界：V4 动态推荐 <code>bcrd_budget</code>（+3.01%）、Legacy 静态 <code>sipp_batch</code>（+2.62% 但耗时高）、V9.1 静态 <code>max_batches=2</code>（+1.53%），并如实交代 V9.1 动态未触发与 <code>trial_budget</code> 平坦现象。</td>
      <td><code>results/core-sensitivity-20261121/REPORT.md</code>、<code>paired.csv</code>、4 张无重叠 SVG、<code>results/v91/</code>、<code>results/bcrd/</code></td>
    </tr>
    <tr>
      <td><b>4. 主线 B 多 Seed 与复评</b></td>
      <td>先给开发集 200 次结果（<code>hga</code> 最低、<code>preview=3</code> 省 46% CPU、仅交叉自适应 +0.94%、变异自适应 86%+ 代触顶），再用既有验证窗 156 次复评反证：<code>hga</code>（−1.12%）、<code>wide_adapt01</code>（−0.54%）与 <code>gate_gen24</code>（−1.41%）均未带来跨窗增益，最终有理有据保留 <code>gate</code>（触发少 63%）。</td>
      <td><code>results/wepa-dev-sensitivity-20261120/REPORT.md</code>（含去重叠 <code>pareto.png</code> 与 2×2 图）、<code>results/wepa-val-sensitivity-20261121/REPORT.md</code>（含 bootstrap 区间）</td>
    </tr>
    <tr>
      <td><b>5. 局限与工程复现</b></td>
      <td>明确 4 来源日描述性边界、回顾性复评口径、课程网格假设；展示零三方依赖核心包、本地 Web 回放与一键校验流程。</td>
      <td><code>README.md</code>、<code>docs/usage.md</code>、<code>results/README.md</code>、<code>src/agv/web/</code></td>
    </tr>
  </tbody>
</table>

<h3>2. 统一复现与演示命令（全仓统一 <code>uv run</code>）</h3>
<pre># 1. 环境安装与本地 Web 回放演示
uv sync --extra dev
uv run agv serve                                 # 浏览器可交互查看 Legacy / V4 / V9 / V9.1 调度过程

# 2. 单案例快速演示（主线 A 与主线 B）
uv run agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 --algorithm bcrd_budget --output runs/v4.json
uv run python research/recommended-20261024/current/run.py --case wepa-day45-bin4335 --seed 0 --output runs/wepa.json

# 3. 工程质量与冻结证据校验
make check                                       # ruff lint + 格式检查 + 全部单元与集成测试
make coverage                                    # 核心模块覆盖率（门槛 80%）
node --check src/agv/web/static/app.js &amp;&amp; node scripts/check_viewer_contracts.mjs
uv run python research/recommended-20261024/verification/verify.py
uv run python scripts/verify_sensitivity_evidence.py verify results/wepa-dev-sensitivity-20261120

# 4. 重跑敏感性实验与重建本总结 PDF（均写入 runs/ 或显式覆盖目标）
uv run python scripts/run_core_sensitivity.py --output runs/core-check --workers 6
uv run python scripts/run_wepa_validation_sensitivity.py --output runs/wepa-val-check --workers 6
uv run python scripts/build_team_summary_pdf.py --overwrite</pre>

<div class="callout-warn" style="margin-top:6px;">
  <b>撰写实验文档的 4 条红线</b>：① 不使用“统计显著”“未见测试”“全局最优”等超出 4 来源日/回顾性复评证据的措辞；② 全文统一“正数 = 改善率（F 降低）”，不混用正负号；③ 不跨协议或跨窗口长度直接对比绝对 F；④ 不挑单 seed 最好值，统一报多 seed 均值 ± SD 与同 seed 配对胜/平/负。
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
