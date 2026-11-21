#!/usr/bin/env python3
"""Build the Chinese PDF from frozen sensitivity evidence; never run a solver.

Requires ReportLab (available in the Codex bundled Python), not a production
dependency. First create STUDY/report with report_sensitivity_study.py. Existing
PDFs are never overwritten. The default destination is output/pdf/STUDY_ID.pdf.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import shlex
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
FIGURES = (
    "core_metrics",
    "paired_effects",
    "seed_stability",
    "sensitivity",
    "budget_2x2",
    "adaptive_2x2",
    "pareto",
    "weight_rescore",
)
INK = colors.HexColor("#173442")
BLUE = colors.HexColor("#21617a")
PALE = colors.HexColor("#edf4f7")
GRAY = colors.HexColor("#53636c")
LINE = colors.HexColor("#cfdae0")
WIDTH = A4[0] - 92


class ParetoPlot(Flowable):
    """Draw exact aggregate points; label only the frontier to avoid collisions."""

    def __init__(self, rows):
        super().__init__()
        self.rows = [row for row in rows if row["complete"]]
        self.width, self.height = WIDTH, 290

    def draw(self):
        pdf = self.canv
        left, bottom, width, height = 49, 37, self.width - 66, 222
        values = [row["ranking_means"] for row in self.rows]
        if not values:
            return
        xmax = max(row["cpu"] for row in values) * 1.15 or 1
        low, high = min(row["F"] for row in values), max(row["F"] for row in values)
        padding = (high - low) * 0.12 or 0.01
        ymin, ymax = low - padding, high + padding
        pdf.setFont("Helvetica", 9.2)
        pdf.setFillColor(INK)
        pdf.drawCentredString(
            self.width / 2, self.height - 11, "Quality / computation Pareto | common planned seeds"
        )
        for step in range(5):
            x, y = left + width * step / 4, bottom + height * step / 4
            pdf.setStrokeColor(LINE)
            pdf.setLineWidth(0.35)
            pdf.line(left, y, left + width, y)
            pdf.setFillColor(GRAY)
            pdf.setFont("Helvetica", 7.6)
            pdf.drawRightString(left - 6, y - 2.5, f"{ymin + (ymax - ymin) * step / 4:.3f}")
            pdf.drawCentredString(x, bottom - 13, f"{xmax * step / 4:.1f}")
        pdf.setStrokeColor(GRAY)
        pdf.setLineWidth(0.65)
        pdf.line(left, bottom, left + width, bottom)
        pdf.line(left, bottom, left, bottom + height)
        pdf.setFont("Helvetica", 8.3)
        pdf.drawCentredString(left + width / 2, 7, "Mean cumulative CPU (s / window)")
        pdf.saveState()
        pdf.translate(11, bottom + height / 2)
        pdf.rotate(90)
        pdf.drawCentredString(0, 0, "Mean F (lower is better)")
        pdf.restoreState()
        for row in self.rows:
            means = row["ranking_means"]
            x = left + means["cpu"] / xmax * width
            y = bottom + (means["F"] - ymin) / (ymax - ymin) * height
            efficient = row["pareto_efficient"]
            pdf.setFillColor(colors.HexColor("#297b58" if efficient else "#7994a1"))
            pdf.circle(x, y, 2.7, stroke=0, fill=1)
            if efficient:
                pdf.setFillColor(INK)
                pdf.setFont("Helvetica", 8)
                pdf.drawString(x + 5, y + 4, row["variant"])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value, digits=4):
    return f"{value:.{digits}f}" if number(value) else "缺失"


def percent(value, digits=3):
    return fmt(value, digits) + "%" if number(value) else "缺失"


def signed(value, digits=4):
    return f"{value:+.{digits}f}" if number(value) else "缺失"


def interval(value):
    return f"[{fmt(value[0], 3)}, {fmt(value[1], 3)}]" if value else "缺失"


def seeds(values):
    return ", ".join(map(str, values))


def register_fonts(font=None):
    """Prefer embedded TrueType fonts; retain an explicit portable CID fallback."""
    candidates = [Path(font)] if font else []
    candidates += [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    errors = []
    chosen = None
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("StudyBody", str(path), subfontIndex=0))
            chosen = path
            break
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    if chosen is None:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        print(
            "WARNING: using unembedded STSong-Light CID fallback; for a distributable "
            "PDF use --font with a CJK TrueType font. " + "; ".join(errors),
            file=sys.stderr,
        )
        return "STSong-Light", "STSong-Light", False
    heading_path = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    try:
        pdfmetrics.registerFont(TTFont("StudyHeading", str(heading_path), subfontIndex=0))
        heading = "StudyHeading"
    except Exception:
        heading = "StudyBody"
    return "StudyBody", heading, True


def load_evidence(study, report):
    """Reject stale summaries and changed trial inputs before composing pages."""
    required = [
        study / "plan.json",
        report / "aggregate.json",
        report / "summary.csv",
        report / "paired.csv",
        report / "中文实验报告.md",
        *(report / "figures" / f"{name}.png" for name in FIGURES),
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"Required evidence is absent: {path}")
    before = {str(path): sha(path) for path in required}
    plan = json.loads((study / "plan.json").read_text(encoding="utf-8"))
    result = json.loads((report / "aggregate.json").read_text(encoding="utf-8"))
    if result.get("schema") != "agv-sensitivity-analysis-v1":
        raise ValueError("Unsupported aggregate schema")
    if plan["study_id"] != result["study_id"]:
        raise ValueError("Study ID mismatch between plan and aggregate")
    if result.get("weight_rescore", {}).get("reoptimized") is not False:
        raise ValueError("Expected read-only rescoring, with reoptimized=false")
    expected_variants = [row["id"] for row in plan["variants"]]
    if [row["variant"] for row in result["variants"]] != expected_variants:
        raise ValueError("Variant sequence differs between plan and aggregate")
    source_hashes = result.get("input_sha256")
    if not source_hashes or "plan.json" not in source_hashes:
        raise ValueError("Aggregate is missing its plan/trial provenance hashes")
    for relative, expected_hash in source_hashes.items():
        path = (study / relative).resolve()
        if not path.is_relative_to(study):
            raise ValueError(f"Input hash escapes study: {relative}")
        if not path.is_file() or sha(path) != expected_hash:
            raise ValueError(f"Study evidence changed since aggregation: {relative}")
    with (report / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        summary = list(csv.DictReader(stream))
    with (report / "paired.csv").open(encoding="utf-8-sig", newline="") as stream:
        paired = list(csv.DictReader(stream))
    if len(summary) != len(result["variants"]) or len(paired) != len(result["paired"]):
        raise ValueError("CSV row counts disagree with aggregate")
    for left, right in zip(summary, result["variants"]):
        if left["variant"] != right["variant"] or left["status"] != right["status"]:
            raise ValueError("summary.csv variant/status mismatch")
        for name, value in right["means"].items():
            if (value is None and left[name] != "") or (
                value is not None and float(left[name]) != value
            ):
                raise ValueError(f"summary.csv differs for {right['variant']}.{name}")
    for left, right in zip(paired, result["paired"]):
        for key, value in right.items():
            if value is None:
                matches = left[key] == ""
            elif number(value):
                matches = float(left[key]) == value
            else:
                matches = left[key] == str(value)
            if not matches:
                raise ValueError(f"paired.csv differs for {key}")
    if any(sha(Path(path)) != value for path, value in before.items()):
        raise ValueError("Report inputs changed while loading")
    return plan, result, before


class Report:
    def __init__(self, plan, result, study, directory, evidence, body, heading, embedded):
        self.plan, self.result = plan, result
        self.study, self.directory, self.evidence = study, directory, evidence
        self.body, self.heading, self.embedded = body, heading, embedded
        self.story = []
        self.configs = {row["id"]: row for row in plan["variants"]}
        self.variants = {row["variant"]: row for row in result["variants"]}
        self.comparisons = {
            (row["candidate"], row["baseline"]): row for row in result["comparisons"]
        }
        self.styles = {
            "title": ParagraphStyle(
                "title", fontName=heading, fontSize=23, leading=31, textColor=INK, spaceAfter=16
            ),
            "h1": ParagraphStyle(
                "h1", fontName=heading, fontSize=16, leading=22, textColor=INK, spaceAfter=12
            ),
            "h2": ParagraphStyle(
                "h2",
                fontName=heading,
                fontSize=11,
                leading=16,
                textColor=BLUE,
                spaceBefore=9,
                spaceAfter=5,
            ),
            "body": ParagraphStyle(
                "body",
                fontName=body,
                fontSize=9.2,
                leading=15.2,
                textColor=INK,
                spaceAfter=8,
                wordWrap="CJK",
            ),
            "small": ParagraphStyle(
                "small",
                fontName=body,
                fontSize=7.8,
                leading=11.7,
                textColor=GRAY,
                spaceAfter=6,
                wordWrap="CJK",
            ),
            "cell": ParagraphStyle(
                "cell", fontName=body, fontSize=7.4, leading=10.6, textColor=INK, wordWrap="CJK"
            ),
            "headcell": ParagraphStyle(
                "headcell",
                fontName=heading,
                fontSize=7.4,
                leading=11,
                textColor=colors.white,
                wordWrap="CJK",
            ),
            "mono": ParagraphStyle(
                "mono",
                fontName=body,
                fontSize=6.9,
                leading=10,
                textColor=INK,
                spaceAfter=7,
                splitLongWords=True,
            ),
            "caption": ParagraphStyle(
                "caption",
                fontName=body,
                fontSize=8,
                leading=12,
                textColor=GRAY,
                spaceBefore=4,
                spaceAfter=9,
                wordWrap="CJK",
            ),
        }

    def p(self, text, style="body"):
        self.story.append(Paragraph(escape(str(text)), self.styles[style]))

    def page(self, title, kicker):
        if self.story:
            self.story.append(PageBreak())
        self.p(kicker, "small")
        self.p(title, "h1")

    def table(self, headers, rows, widths, *, font_size=None):
        def paragraph(value, header=False):
            style = self.styles["headcell" if header else "cell"]
            if font_size:
                style = ParagraphStyle(
                    "compact", parent=style, fontSize=font_size, leading=font_size + 3
                )
            return Paragraph(escape(str(value)), style)

        data = [[paragraph(value, True) for value in headers]]
        data += [[paragraph(value) for value in row] for row in rows]
        table = Table(
            data,
            colWidths=[WIDTH * value / sum(widths) for value in widths],
            repeatRows=1,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, BLUE),
                    ("LINEBELOW", (0, -1), (-1, -1), 0.4, LINE),
                ]
            )
        )
        self.story.extend([table, Spacer(1, 8)])

    def figure(self, name, caption, max_height=245):
        path = self.directory / "figures" / f"{name}.png"
        width, height = ImageReader(str(path)).getSize()
        scale = min(WIDTH / width, max_height / height)
        image = Image(str(path), width=width * scale, height=height * scale)
        image.hAlign = "CENTER"
        self.story.append(KeepTogether([image, Paragraph(escape(caption), self.styles["caption"])]))

    def comparison_rows(self, pairs):
        rows = []
        for candidate, baseline in pairs:
            row = self.comparisons.get((candidate, baseline))
            if not row:
                continue
            rows.append(
                [
                    f"{candidate} / {baseline}",
                    percent(row["mean_paired_F_gain_percent"]),
                    interval(row["F_gain_date_bootstrap_95ci"]),
                    f"{row['wins']}/{row['ties']}/{row['losses']}" if row["complete"] else "不完整",
                ]
            )
        return rows

    def executive(self):
        result = self.result
        self.p("AGV 调度研究 · 冻结证据报告", "small")
        self.p("多 seed 稳定性与参数敏感性", "title")
        self.p(result["study_id"], "small")
        created = self.plan.get("created_utc", "未记录")
        self.p(
            f"计划冻结时间（UTC）：{created}；计算结果及统计均来自当前 study/report，不生成模拟结果。"
        )
        valid = sum(row["valid"] for row in result["variants"])
        failed = sum(row["failed"] for row in result["variants"])
        self.table(
            ["计划运行", "已记录 / 有效", "来源日期 / 窗口", "分析状态"],
            [
                [
                    result["planned_trials"],
                    f"{result['observed_trials']} / {valid}",
                    f"{result['source_date_count']} / {result['case_count']}",
                    "完整" if result["complete"] else "存在不完整项",
                ]
            ],
            [1, 1.3, 1.3, 1.3],
        )
        self.p("从本轮证据能够得到什么", "h2")
        core = [
            row
            for row in result["variants"]
            if row["group"] in ("evolution", "core") and row["complete"]
        ]
        if core:
            best = min(core, key=lambda row: row["means"]["F"])
            self.p(
                f"在既有开发窗口的核心七方案中，{best['variant']} 的等权日期平均 F 最低，为 {fmt(best['means']['F'])}；"
                f"平均累计 CPU 为 {fmt(best['means']['cpu'], 3)} 秒/窗口。各方案 seed 数不同，"
                f"资源与全体方案的公平排名另以预声明共同 seed [{seeds(result['ranking_seeds'])}] 核验。"
            )
        else:
            self.p("核心方案未形成可排名的完整证据；本报告保留失败和缺失，不以成功子样本宣称最优。")
        self.p(
            f"有效运行 {valid} 次；已记录但无效/失败 {failed} 次，缺失 {len(result['missing_trials'])} 次，"
            f"非计划记录 {len(result['unexpected_trials'])} 次。缺失或失败使对应方案及配对比较不完整，"
            "相应均值、排名和改善率留空。"
        )
        self.table(
            ["候选 / 基线", "平均 F 改善", "日期描述性 95% 区间", "胜/平/负日期"],
            self.comparison_rows(
                [
                    ("wide", "simple"),
                    ("gate", "wide"),
                    ("hga", "gate"),
                    ("hungarian", "gate"),
                    ("gate", "eta"),
                    ("gate", "fcfs"),
                ]
            ),
            [1.8, 1, 1.4, 1],
        )
        self.p(
            "改善率为每个日期的 100 × (1 - 候选 F / 基线 F)，再对日期等权平均；正值表示 F 下降。区间按来源日期重采样，仅描述这几个开发日期的波动。",
            "small",
        )
        findings = []
        for candidate, baseline, label in (
            ("gate_gen8", "gate", "代数从 16 减至 8"),
            ("wide_adapt11", "wide_adapt00", "同时打开两个自适应开关"),
        ):
            comparison = self.comparisons.get((candidate, baseline))
            if comparison and comparison["complete"]:
                findings.append(
                    f"{label}的平均 F 改善为 "
                    f"{percent(comparison['mean_paired_F_gain_percent'])}"
                    f"（日期胜/平/负 {comparison['wins']}/{comparison['ties']}/{comparison['losses']}）"
                )
        if findings:
            self.p("；".join(findings) + "。固定预算和开关对照见第 5、6 节。", "small")
        self.p(
            "本研究是“真实订单片段驱动的项目仿真”：所有窗口均为既有 development 数据；不构成未见验证、工业实测或跨场景泛化证据。本轮结果不自动替换默认算法。"
        )
        self.figure(
            "sensitivity",
            "图 1 · 预算与自适应矩阵概览：各方案全部预声明 seed 的日期等权 F / CPU 均值。受控共同 seed 对照见第 5、6 节。",
            172,
        )

    def protocol(self):
        self.page("模型口径、数据与统计边界", "02 / 数据与方法")
        objective = self.plan.get("objective", {})
        self.p("公开订单来源与项目模型", "h2")
        self.p(
            "订单片段来源于 SLAPStack / WEPAStacks 公开真实订单流，按本项目规则映射到 large 62×47 栅格、6 辆车、5 层货架模型；货位映射使用固定 random.Random(17)。原场地堆叠至 3 层，与本模型不同；这里没有复刻原仓完整地图或三个月全量生产。"
        )
        horizon = objective.get("horizon_seconds", 900)
        self.p(
            f"统一窗口长度 {fmt(horizon, 0)} 秒。车辆、任务、SIPP 预约冲突规则、物理目标和输入快照在全部方案间一致。评估 seed 改变搜索随机性，不改变源订单或固定货位映射。"
        )
        provenance = self.plan.get("case_provenance", {})
        cases = [item["case"] if isinstance(item, dict) else item for item in self.plan["cases"]]
        task_counts = [provenance.get(case, {}).get("tasks") for case in cases]
        if all(type(count) is int for count in task_counts):
            self.p(
                f"这些窗口合计 {sum(task_counts)} 条唯一源请求。{self.result['planned_trials']} 次方法/seed 运行反复使用同一批窗口，不是 {self.result['planned_trials']} 个独立业务场景。",
                "small",
            )
        self.table(
            ["固定开发窗口", "来源日", "订单数", "角色"],
            [
                [
                    case,
                    provenance.get(case, {}).get("source_day", "未记录"),
                    provenance.get(case, {}).get("tasks", "未记录"),
                    "既有 development",
                ]
                for case in cases
            ],
            [2.7, 0.7, 0.7, 1.2],
        )
        self.p("目标与时间、距离的定义", "h2")
        self.p(
            f"计划目标配置：{json.dumps(objective, ensure_ascii=False, sort_keys=True)}", "small"
        )
        self.p(
            "T 为最后一个订单完成时刻，不含末次返库；R 为订单完成时刻减发布时间的均值；D 为累计移动距离，包含末次返库。主目标按统一尺度对 T、R、D 线性加权。CPU 为整个模拟执行累计计算时间，不能解释为物理运输时间或单次在线决策延迟。"
        )
        self.p("配对、聚合与不确定性", "h2")
        self.p(
            f"先在相同 case 内平均 seed，再在同一来源日期内平均窗口，最后对 {self.result['source_date_count']} 个来源日期等权。配对使用预声明 case/seed 交集；seed 重复不增加独立业务日期。95% bootstrap 区间只按来源日期重采样，不表示显著性或总体置信保证。"
        )
        groups = {}
        for row in self.plan["variants"]:
            key = row.get("group", ""), tuple(row.get("seeds", self.plan["seeds"]))
            groups.setdefault(key, []).append(row["id"])
        self.table(
            ["方案", "实验组", "预声明评估 seed"],
            [[", ".join(names), group, seeds(values)] for (group, values), names in groups.items()],
            [3.5, 0.9, 1.4],
            font_size=6.8,
        )
        python_version = self.plan.get("environment", {}).get("python", "未记录").split()[0]
        workers = self.plan.get("limits", {}).get("max_workers", "未记录")
        self.p(
            f"本轮执行环境：macOS arm64、Apple M5、10 逻辑 CPU、24 GiB RAM；Python {python_version}；"
            f"最多 {workers} 个实验子进程。CPU 对照受具体硬件与并发负载影响。",
            "small",
        )

    def core(self):
        self.page("七方案演进：质量与计算代价", "03 / 统一输入核心比较")
        self.p(
            "fcfs、eta、simple、wide、gate、hga、hungarian 统一输入与物理评价；simple → wide 是整组搜索预算变化，不是单参数因果实验。各图只使用完整方案。"
        )
        self.figure(
            "core_metrics",
            "图 2 · 核心七方案的等权日期均值；F 越低越好，T/R/P90 单位为秒，D 单位为栅格，CPU 为秒/窗口。各方案均使用其全部预声明 seed。",
            282,
        )
        core = [row for row in self.result["variants"] if row["group"] in ("evolution", "core")]
        self.table(
            ["方案", "有效/计划", "F", "T (s)", "R (s)", "D (cells)", "CPU (s)", "seed SD"],
            [
                [
                    row["variant"],
                    f"{row['valid']}/{row['expected']}",
                    *(fmt(row["means"][metric], 3) for metric in ("F", "T", "R", "D", "cpu")),
                    fmt(row["F_seed_sd_mean"], 5),
                ]
                for row in core
            ],
            [1.2, 1, 0.9, 1, 1, 1.2, 1.05, 1],
            font_size=6.9,
        )
        self.p(
            "表中 seed SD 是每窗口内 F 的样本标准差，再按日期等权汇总；日期 SD 与 seed SD 衡量不同来源的波动。确定性方法更换 seed 后成绩相同是算法特性，不说明业务环境没有变动。"
        )
        self.p(
            "图中 P90 先由每次窗口/seed 运行的任务响应计算，再按 seed、窗口和日期等权汇总；不是把全部重复任务池化后的单一 90 分位数。",
            "small",
        )
        self.p(
            "方案名称代表本项目的具体实现及配置，不能据此给同名算法的一切实现作普遍排序。七方案全 seed 均值用于方案稳定性；Pareto 和权重比较另固定共同 seed，避免重复数量不同改变比较口径。",
            "small",
        )

    def pairing(self):
        self.page("固定配对效果与 seed 波动", "04 / 差异与稳定性")
        self.p(
            f"同一 case/seed 固定配对，不挑选最佳 seed；相同 eval_seed 不保证不同算法的随机数调用序列一致。点表示各来源日期；深色点和线表示日期均值及描述性 bootstrap 区间，统计单位 n={self.result['source_date_count']}。"
        )
        self.figure(
            "paired_effects",
            "图 3 · 计划显式声明的对照。横轴正值表示候选 F 低于基线；接近零、跨零或日期间异号均应如实解释，不能读作显著获益。",
            319,
        )
        self.figure(
            "seed_stability",
            "图 4 · 核心方案每个窗口内 F 随 seed 变化的样本标准差。短横线为窗口 SD 的均值；这是随机搜索稳定性，不是独立训练稳定性。",
            187,
        )
        self.p(
            "日期与 seed 是两层重复：同一批真实订单重复执行只能检验求解随机性。原始逐配对结果保存在 paired.csv，包含所有共同基线及显式对照，且保留负改善。",
            "small",
        )

    def factorial(self, name):
        return next((row for row in self.result["factorials"] if row["name"] == name), None)

    def factorial_effects(self, name):
        factorial = self.factorial(name)
        if not factorial or not factorial["complete"]:
            return [["不完整", "缺失", "缺失"]]
        xs, ys = factorial["x_levels"], factorial["y_levels"]
        lookup = {(row["x"], row["y"]): row["means"] for row in factorial["cells"]}
        effects = []
        for label, coefficients in [
            ("x 主效应：高 - 低", {(xs[1], y): 0.5 for y in ys} | {(xs[0], y): -0.5 for y in ys}),
            ("y 主效应：高 - 低", {(x, ys[1]): 0.5 for x in xs} | {(x, ys[0]): -0.5 for x in xs}),
            (
                "交互：差中之差",
                {(xs[1], ys[1]): 1, (xs[0], ys[1]): -1, (xs[1], ys[0]): -1, (xs[0], ys[0]): 1},
            ),
        ]:
            effects.append(
                [
                    label,
                    *(
                        signed(
                            sum(
                                lookup[key][metric] * coefficient
                                for key, coefficient in coefficients.items()
                            ),
                            5 if metric == "F" else 3,
                        )
                        for metric in ("F", "cpu")
                    ),
                ]
            )
        return effects

    def budget(self):
        self.page("搜索预算：2×2 资源组合与代数", "05 / 参数敏感性")
        factorial = self.factorial("budget_2x2")
        self.p(
            f"资源组合固定 generations=16，proxy cap∈{{96,192}}、full-preview cap∈{{3,6}}；四格统一 seed [{seeds(factorial['paired_seeds']) if factorial else '缺失'}]。上限不一定用满，应同时查看实际搜索消耗。"
        )
        self.figure(
            "budget_2x2", "图 5 · 左为 F，右为 CPU；横轴 proxy 上限，纵轴完整预演上限。", 196
        )
        self.table(
            ["四格代数效应（高 - 低）", "ΔF", "ΔCPU (s)"],
            self.factorial_effects("budget_2x2"),
            [2.6, 1.2, 1.2],
        )
        self.p(
            "主效应为另一因子两水平的平均差，交互为差中之差。ΔF 为负表示目标降低，与“正改善率”符号相反；这些是描述性代数对照。",
            "small",
        )
        self.table(
            ["候选 / gate", "平均 F 改善", "日期描述性 95% 区间", "胜/平/负日期"],
            self.comparison_rows(
                [
                    (name, "gate")
                    for name in (
                        "gate_proxy96",
                        "gate_preview3",
                        "gate_proxy96_preview3",
                        "gate_gen8",
                    )
                ]
            ),
            [1.9, 1, 1.5, 1],
        )
        self.p(
            "gate_gen8 / gate 只把代数从 16 减至 8，其他上限不变；配对结果描述本轮代数边际变化，不能外推最优代数。",
            "small",
        )
        rows = []
        for variant in (
            "gate",
            "gate_proxy96",
            "gate_preview3",
            "gate_proxy96_preview3",
            "gate_gen8",
        ):
            row = self.variants[variant]
            search = row["search_totals"]
            rows.append(
                [
                    variant,
                    search["searches"],
                    search["proxy_evaluations"],
                    search["previews"],
                    f"{search['proxy_cap_hits']}/{search['preview_cap_hits']}",
                ]
            )
        self.table(
            ["方案", "searches", "proxy 评分", "previews", "上限触发 P/V"],
            rows,
            [2, 0.9, 1.1, 1, 1.1],
            font_size=6.8,
        )
        self.p(
            "实际消耗为各方案全部有效 trial 的累计总数；gate 的计划 seed 较多，累计值不用于直接判断每窗口资源优劣。CPU/F 对照使用共同 seed。",
            "small",
        )

    def adaptive(self):
        self.page("自适应算子：受控的 2×2 开关", "06 / 移植方案与机制对照")
        factorial = self.factorial("adaptive_2x2")
        self.p(
            f"同一移植后的 GA 实现、相同初值 pm=0.7、pc=0.9；横轴为 mutation 自适应开关，纵轴为 crossover 自适应开关。四格共同 seed [{seeds(factorial['paired_seeds']) if factorial else '缺失'}]。"
        )
        self.figure(
            "adaptive_2x2",
            "图 6 · 00 为两个开关关闭；10/01/11 分别为 mutation、crossover、二者同时自适应。左为 F，右为 CPU。",
            242,
        )
        self.table(
            ["候选 / 基线", "平均 F 改善", "日期描述性 95% 区间", "胜/平/负日期"],
            self.comparison_rows(
                [(f"wide_adapt{code}", "wide_adapt00") for code in ("10", "01", "11")]
                + [("wide_adapt11", "wide")]
            ),
            [2, 1, 1.5, 1],
        )
        self.table(
            ["四格代数效应（开 - 关）", "ΔF", "ΔCPU (s)"],
            self.factorial_effects("adaptive_2x2"),
            [2.6, 1.2, 1.2],
        )
        both, cross = self.variants["wide_adapt11"], self.variants["wide_adapt01"]
        if both["complete"] and cross["complete"]:
            baseline_dates = {row["day"]: row for row in cross["dates"]}
            gains = [
                100 * (1 - row["means"]["F"] / baseline_dates[row["day"]]["means"]["F"])
                for row in both["dates"]
            ]
            gain = sum(gains) / len(gains)
            interpretation = (
                "本轮单开交叉比双开更有希望，两个开关没有叠加获益"
                if gain < 0
                else "本轮双开相对单开交叉的效果仍只适用于这些历史开发日期"
            )
            self.p(
                f"双开 / 只开交叉（11/01）的逐日期平均 F 改善为 {percent(gain, 6)}；{interpretation}。",
                "small",
            )
        saturation = {
            name: dict(total=0, capped=0, searches=0, capped_searches=0)
            for name in ("wide_adapt10", "wide_adapt11")
        }
        for relative in self.result["input_sha256"]:
            if not relative.startswith("trials/"):
                continue
            trial = json.loads((self.study / relative).read_text(encoding="utf-8"))
            if trial["variant"] not in saturation:
                continue
            record = saturation[trial["variant"]]
            for activity in trial.get("search", {}).get("operator_activity", []):
                history = activity.get("mutation_history", [])
                capped = sum(abs(row.get("mutation_rate", -1) - 0.95) < 1e-9 for row in history)
                record["total"] += len(history)
                record["capped"] += capped
                record["searches"] += 1
                record["capped_searches"] += int(capped > 0)
        observations = []
        for name, record in saturation.items():
            if record["total"]:
                observations.append(
                    f"{name} 有 {record['capped']}/{record['total']} 代 mutation_rate=0.95（{percent(100 * record['capped'] / record['total'], 2)}），{record['capped_searches']}/{record['searches']} 次搜索至少一次饱和"
                )
        if observations:
            self.p(
                "逐代日志机制核验："
                + "；".join(observations)
                + "。这些记录说明该规则在此数据上经常触顶，不能直接视为调优建议。",
                "small",
            )
        self.p(
            "10/00、01/00、11/00 在同一实现内检查开关作用。原 wide 交叉必定执行，adapt00 则使用新算子且固定 pc=0.9；wide_adapt11 / wide 还改变遗传算子实现和随机调用路径，是整组移植方案比较，不能把其全部差异归因于“自适应”二字。"
        )
        self.p(
            "这组实验移植了后续自适应 GA 算子，没有训练或重训 DQN，没有恢复历史 DQN 完整运行链。本轮多 seed 是评估 seed，不是从零初始化的训练 seed；不能据此证明学习稳定性。"
        )

    def pareto(self):
        self.page("CPU / F 权衡与物理分量解释", "07 / 资源与质量")
        self.p(
            f"全体方案固定共同 seed [{seeds(self.result['ranking_seeds'])}]，先 seed、后日期等权。绿色表示在这批成绩中没有其他完整方案能同时做到 F、CPU 均不更大且至少一项更小。"
        )
        self.story.append(ParetoPlot(self.result["variants"]))
        self.p(
            "图 7 · 依 aggregate 的共同 seed 均值绘制全部完整方案；绿色为非支配，灰色为其余。为避免密集标签重叠，仅标注 Pareto 方案。左下方向更优；这不等于工业部署推荐。",
            "caption",
        )
        efficient = [row for row in self.result["variants"] if row["pareto_efficient"]]
        self.p(
            "本轮 Pareto 集："
            + ("、".join(row["variant"] for row in efficient) if efficient else "无完整可比较方案")
            + "。"
        )
        chosen = [
            row
            for row in self.result["variants"]
            if row["variant"] in {"gate", "wide", "eta", "hungarian"} or row["pareto_efficient"]
        ]
        self.table(
            ["方案", "共同 seed F", "T (s)", "R (s)", "D (cells)", "CPU (s)"],
            [
                [
                    row["variant"],
                    *(
                        fmt(row["ranking_means"][metric], 3)
                        for metric in ("F", "T", "R", "D", "cpu")
                    ),
                ]
                for row in chosen
            ],
            [1.8, 1.2, 1, 1, 1.3, 1.1],
            font_size=6.9,
        )
        self.p(
            "F 是归一化后的综合目标。判断改进由什么驱动，需同时看最后订单完成 T、平均响应 R 和总距离 D；某一分量变好不要求其余分量也变好。D 含末返库而 T 不含，因此 T/D 的变动不应按相同终点解释。",
            "small",
        )
        self.p(
            "CPU 是该硬件、运行时与共享负载下的累计值，不是算法复杂度证明；本轮限时失败会进入状态统计，不能从资源图中静默删除后再排名。",
            "small",
        )

    def weights(self):
        self.page("权重稳健性：同轨迹只读重评分", "08 / 偏好变化")
        self.p(
            f"固定共同 seed [{seeds(self.result['ranking_seeds'])}]，读取同一批轨迹的 T/R/D，改变线性偏好权重后重新计分。没有重优化、重新训练或重跑调度；排名变化仅描述既有轨迹对评价偏好的敏感性。"
        )
        self.figure(
            "weight_rescore",
            "图 8 · 四种评价偏好下核心七方案在全体完整方案中的名次；越上方名次越靠前。折线不是新权重下重新求解的成绩。",
            268,
        )
        scenarios = self.result["weight_rescore"]["scenarios"]
        rows = []
        for variant in self.variants:
            scores = [
                next(row for row in scenario["scores"] if row["variant"] == variant)
                for scenario in scenarios
            ]
            rows.append(
                [
                    variant,
                    *(
                        f"{row['rank']} / {fmt(row['score'], 4)}"
                        if row["rank"] is not None
                        else "缺失"
                        for row in scores
                    ),
                ]
            )
        self.table(
            [
                "方案",
                *(
                    f"{scenario['label']}\n{'/'.join(map(str, scenario['weights']))}"
                    for scenario in scenarios
                ),
            ],
            rows,
            [1.8, 1.25, 1.25, 1.25, 1.25],
            font_size=6.7,
        )
        self.p(
            "每格为“名次 / 重评分”。同分允许并列；排名依据 score，不根据图上折线先后。若要声称适应新目标，需要在预先划定的新任务/权重上重新求解并另行评价。",
            "small",
        )

    def reproducibility(self, output):
        self.page("局限、复现命令与来源指纹", "09 / 审计与复现")
        self.p("解释限制", "h2")
        self.p(
            "全部窗口为既有开发数据，且曾参与项目开发选择；日期数少，不能支持统计显著、未见泛化或真实整仓生产收益。模型中的货位、层数与运动规则是课程项目假设，真实的是订单片段来源。"
        )
        self.p(
            "原历史 DQN 的窗口长度、训练过程与五日期证据单独封存，不与本轮 15 分钟窗口的绝对 F 混排。本报告不引用未经本轮同口径验证的历史百分比。"
        )
        self.p(
            "最初 5/200 预检因 runner 格式与 Windows 可移植性修正中止，保留在 ignored runs/sensitivity-20261120/aborted-preflight-study，不纳入正式 v2；求解参数与窗口选择未据预检调优。"
        )
        self.p(
            "失败/缺失按计划总数计入；某方案有任何计划 trial 无效就不作成功子样本排名。CPU 受硬件和负载影响；日期 bootstrap 是描述区间。当前结果不自动改变生产默认。",
            "small",
        )
        self.p("复现（仓库根目录；输出必须为新路径）", "h2")
        study_arg = os.path.relpath(self.study, ROOT)
        report_arg = os.path.relpath(self.directory, ROOT)
        self.p(
            f"python scripts/verify_sensitivity_evidence.py verify {shlex.quote(study_arg)}",
            "mono",
        )
        self.p(
            f".venv/bin/python scripts/report_sensitivity_study.py {shlex.quote(study_arg)} --output output/sensitivity-report-new",
            "mono",
        )
        self.p(
            f"python scripts/build_sensitivity_pdf.py {shlex.quote(study_arg)} --report {shlex.quote(report_arg)} --output output/pdf/sensitivity-report-new.pdf",
            "mono",
        )
        self.p(
            "便携 verify 只依赖标准库和本研究目录，核对归档与记录一致性，不重跑物理验解。重新绘图需项目 plots 依赖，PDF 需 ReportLab。完整环境准备和 200 次重跑命令见 docs/research/multiseed-sensitivity-20261120.md；表内四格效应是 aggregate 的代数派生。",
            "small",
        )
        self.p("SHA-256 来源指纹", "h2")
        hashes = [
            ("plan.json", sha(self.study / "plan.json")),
            ("aggregate.json", sha(self.directory / "aggregate.json")),
            ("summary.csv", sha(self.directory / "summary.csv")),
            ("paired.csv", sha(self.directory / "paired.csv")),
            ("中文实验报告.md", sha(self.directory / "中文实验报告.md")),
            ("trial 输入 hash 映射", digest(self.result["input_sha256"])),
            (
                "PNG 图 hash 映射",
                digest(
                    {
                        f"{name}.png": sha(self.directory / "figures" / f"{name}.png")
                        for name in FIGURES
                    }
                ),
            ),
            ("分析器源码", self.result.get("reporter_sha256", "未记录")),
            ("PDF 生成器源码", sha(Path(__file__))),
            ("实验 runner 源码", self.plan.get("sources", {}).get("runner", "未记录")),
            ("移植 adaptive 算子", self.plan.get("sources", {}).get("adaptive_operator", "未记录")),
            ("运行时 manifest", self.plan.get("sources", {}).get("runtime_manifest", "未记录")),
        ]
        self.table(["证据", "完整 SHA-256"], hashes, [1.55, 4.6], font_size=6.4)
        self.p(
            "映射指纹 = SHA256(json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode('utf-8'))；trial 各文件指纹可在 aggregate.json 的 input_sha256 逐项核对。PDF 页脚含 study ID，输入文件均在构建前后校验未变。",
            "small",
        )
        if not self.embedded:
            self.p(
                "当前 PDF 使用 CID 后备中文字体，未嵌入。正式交付请使用 --font 指定可嵌入的中文 TrueType 字体重新生成。",
                "small",
            )

    def compose(self, output):
        self.executive()
        self.protocol()
        self.core()
        self.pairing()
        self.budget()
        self.adaptive()
        self.pareto()
        self.weights()
        self.reproducibility(output)
        return self.story


def build(study, output=None, report=None, font=None):
    study = Path(study).resolve()
    report = Path(report).resolve() if report else study / "report"
    plan, result, evidence = load_evidence(study, report)
    output = (
        Path(output).resolve() if output else ROOT / "output" / "pdf" / f"{result['study_id']}.pdf"
    )
    if output.suffix.lower() != ".pdf":
        raise ValueError("Output path must end in .pdf")
    if output.exists():
        raise FileExistsError(f"Refuse to overwrite PDF: {output}")
    body, heading, embedded = register_fonts(font)
    report_builder = Report(plan, result, study, report, evidence, body, heading, embedded)
    story = report_builder.compose(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def page_decoration(pdf, doc):
        pdf.saveState()
        pdf.setStrokeColor(LINE)
        pdf.line(46, A4[1] - 35, A4[0] - 46, A4[1] - 35)
        pdf.line(46, 37, A4[0] - 46, 37)
        pdf.setFillColor(GRAY)
        pdf.setFont("Helvetica", 6.7)
        pdf.drawString(46, 24, result["study_id"])
        pdf.setFont(body, 7)
        pdf.drawRightString(A4[0] - 46, 24, f"第 {doc.page} 页")
        pdf.restoreState()

    class InvariantCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = True
            super().__init__(*args, **kwargs)

    created = False
    try:
        with output.open("xb") as stream:
            created = True
            document = SimpleDocTemplate(
                stream,
                pagesize=A4,
                rightMargin=46,
                leftMargin=46,
                topMargin=49,
                bottomMargin=49,
                title="AGV 多 seed 稳定性与参数敏感性",
                author="AGV project - frozen evidence report",
                subject=result["study_id"],
                pageCompression=1,
            )
            document.build(
                story,
                onFirstPage=page_decoration,
                onLaterPages=page_decoration,
                canvasmaker=InvariantCanvas,
            )
        if any(sha(Path(path)) != value for path, value in evidence.items()):
            raise ValueError("Evidence changed during PDF build")
        for relative, value in result["input_sha256"].items():
            if sha(study / relative) != value:
                raise ValueError(f"Study source changed during PDF build: {relative}")
    except Exception:
        # This process exclusively created the file; incomplete output is not evidence.
        if created and output.exists():
            output.unlink()
        raise
    return dict(
        output=str(output),
        sha256=sha(output),
        study_id=result["study_id"],
        complete=result["complete"],
        embedded_cjk_font=embedded,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path, help="Frozen study containing plan.json and report/")
    parser.add_argument("--output", type=Path, help="New PDF path; existing files are refused")
    parser.add_argument("--report", type=Path, help="Report directory (default: STUDY/report)")
    parser.add_argument(
        "--font", type=Path, help="Optional embeddable CJK TrueType font (.ttf/.ttc)"
    )
    args = parser.parse_args()
    print(json.dumps(build(args.study, args.output, args.report, args.font), ensure_ascii=False))


if __name__ == "__main__":
    main()
