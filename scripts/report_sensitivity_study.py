#!/usr/bin/env python3
"""Analyze a frozen sensitivity study without running or changing its solvers."""

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
from collections import Counter
from pathlib import Path

METRICS = ("F", "T", "R", "D", "p90", "empty_distance", "traffic_wait", "cpu", "wall")
SUCCESS = {"ok", "success", "complete", "completed", "valid"}
WEIGHTS = (
    ("Primary", (0.5, 0.3, 0.2)),
    ("Completion", (0.6, 0.2, 0.2)),
    ("Response", (0.4, 0.4, 0.2)),
    ("Distance", (0.4, 0.2, 0.4)),
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mean(values):
    values = list(values)
    return statistics.mean(values) if values else None


def _sd(values):
    values = list(values)
    return statistics.stdev(values) if len(values) > 1 else None


def source_day(case):
    """Several windows on the same source day remain one analysis cluster."""
    match = re.search(r"(?:^|-)day(\d+)(?:-|$)", case)
    return int(match.group(1)) if match else case


def bootstrap_ci(values, *, samples=4000, seed=20261120):
    """Descriptive percentile interval over dates, never over repeated seeds."""
    values = list(values)
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    boot = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [boot[int(0.025 * (samples - 1))], boot[int(0.975 * (samples - 1))]]


def _valid(trial):
    row = trial.get("row", {})
    return (
        trial.get("status") in SUCCESS
        and row.get("valid") is True
        and all(_number(row.get(name)) and row[name] >= 0 for name in ("F", "T", "R", "D", "cpu"))
    )


def _case_ids(plan):
    return [case["case"] if isinstance(case, dict) else case for case in plan["cases"]]


def _dates(plan, cases):
    declared = {
        item["case"]: item.get("source_day", item.get("day", source_day(item["case"])))
        for item in plan["cases"]
        if isinstance(item, dict)
    }
    provenance = plan.get("case_provenance", {})
    return {
        case: declared.get(case, provenance.get(case, {}).get("source_day", source_day(case)))
        for case in cases
    }


def load_trials(study):
    """Return plan and all raw trial records; input evidence is never rewritten."""
    study = Path(study)
    plan = json.loads((study / "plan.json").read_text(encoding="utf-8"))
    trials = []
    for path in sorted((study / "trials").glob("*.json")):
        trial = json.loads(path.read_text(encoding="utf-8"))
        trial["_source_file"] = str(path.relative_to(study))
        trials.append(trial)
    return plan, trials


def _comparison_specs(plan):
    baseline = plan.get("baseline", "gate")
    result = [
        dict(
            id=f"{item['id']}_vs_{baseline}",
            baseline=baseline,
            candidate=item["id"],
            kind="common_baseline",
        )
        for item in plan["variants"]
        if item["id"] != baseline
    ]
    for item in plan.get("comparisons", []):
        if isinstance(item, (list, tuple)):
            item = dict(candidate=item[0], baseline=item[1])
        item = dict(item)
        item["declared"] = True
        if "reference" in item:
            item["baseline"] = item["reference"]
        item.setdefault("id", f"{item['candidate']}_vs_{item['baseline']}")
        result = [existing for existing in result if existing["id"] != item["id"]]
        result.append(item)
    return result


def analyze(plan, trials):
    """Aggregate equal-weight dates after averaging paired case/seed records.

    Any missing or invalid planned record makes its variant and its comparisons
    incomplete. Partial successful means are deliberately not used for ranking.
    """
    cases = _case_ids(plan)
    seeds = plan["seeds"]
    variants = {item["id"]: item for item in plan["variants"]}
    if len(variants) != len(plan["variants"]) or len(set(cases)) != len(cases):
        raise ValueError("Duplicate planned variant or case")
    if not cases or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Cases and unique seeds must be nonempty")
    if any(type(seed) is not int for seed in seeds):
        raise ValueError("Seeds must be integers")
    day_by_case = _dates(plan, cases)
    days = sorted(set(day_by_case.values()), key=str)
    index, inventory = {}, []
    for trial in trials:
        key = (trial["variant"], trial["case"], trial["seed"])
        if key in index:
            raise ValueError("Duplicate trial key: " + repr(key))
        index[key] = trial
        # The original trial and ZIP retain detailed per-generation activity.
        # Keep its identity and failure evidence here without duplicating every
        # generation in the analytical aggregate.
        inventory.append({name: value for name, value in trial.items() if name != "search"})
        inventory[-1]["analysis_valid"] = _valid(trial)
    expected = {
        (variant, case, seed)
        for variant, config in variants.items()
        for case in cases
        for seed in config.get("seeds", seeds)
    }
    unexpected = [dict(variant=k[0], case=k[1], seed=k[2]) for k in index if k not in expected]
    missing = [dict(variant=k[0], case=k[1], seed=k[2]) for k in sorted(expected - index.keys())]
    summaries = []
    for variant, config in variants.items():
        own_keys = [key for key in sorted(expected) if key[0] == variant]
        good = [index[key] for key in own_keys if key in index and _valid(index[key])]
        complete = len(good) == len(own_keys)
        date_rows = []
        for day in days:
            day_cases = [case for case in cases if day_by_case[case] == day]
            case_rows = []
            for case in day_cases:
                rows = [index.get((variant, case, seed)) for seed in config.get("seeds", seeds)]
                valid = [row["row"] for row in rows if row is not None and _valid(row)]
                case_complete = len(valid) == len(rows)
                metrics = {
                    name: _mean(row[name] for row in valid)
                    if case_complete and all(_number(row.get(name)) for row in valid)
                    else None
                    for name in METRICS
                }
                case_rows.append(
                    dict(
                        case=case,
                        complete=case_complete,
                        expected=len(rows),
                        valid=len(valid),
                        means=metrics,
                        F_seed_sd=_sd(row["F"] for row in valid) if case_complete else None,
                        F_seed_min=min((row["F"] for row in valid), default=None)
                        if case_complete
                        else None,
                        F_seed_max=max((row["F"] for row in valid), default=None)
                        if case_complete
                        else None,
                    )
                )
            day_complete = all(row["complete"] for row in case_rows)
            date_rows.append(
                dict(
                    day=day,
                    complete=day_complete,
                    cases=case_rows,
                    means={
                        name: _mean(row["means"][name] for row in case_rows)
                        if day_complete and all(row["means"][name] is not None for row in case_rows)
                        else None
                        for name in METRICS
                    },
                    F_seed_sd_mean=_mean(
                        row["F_seed_sd"] for row in case_rows if row["F_seed_sd"] is not None
                    )
                    if day_complete
                    else None,
                )
            )
        means = {
            name: _mean(row["means"][name] for row in date_rows)
            if complete and all(row["means"][name] is not None for row in date_rows)
            else None
            for name in METRICS
        }
        summaries.append(
            dict(
                variant=variant,
                profile=config.get("profile"),
                group=config.get("group", ""),
                complete=complete,
                status="complete" if complete else "incomplete",
                expected=len(own_keys),
                observed=sum(key in index for key in own_keys),
                valid=len(good),
                failed=sum(key in index and not _valid(index[key]) for key in own_keys),
                missing=sum(key not in index for key in own_keys),
                dates=date_rows,
                means=means,
                F_date_sd=_sd(row["means"]["F"] for row in date_rows) if complete else None,
                F_seed_sd_mean=_mean(
                    row["F_seed_sd_mean"] for row in date_rows if row["F_seed_sd_mean"] is not None
                )
                if complete
                else None,
                F_date_bootstrap_95ci=bootstrap_ci(row["means"]["F"] for row in date_rows)
                if complete
                else None,
                search_totals={
                    name: sum(trial.get("search", {}).get(name, 0) or 0 for trial in good)
                    for name in (
                        "searches",
                        "proxy_evaluations",
                        "previews",
                        "gate_decisions",
                        "proxy_cap_hits",
                        "preview_cap_hits",
                    )
                },
            )
        )
    paired, comparisons = [], []
    for spec in _comparison_specs(plan):
        base, candidate = spec["baseline"], spec["candidate"]
        if base not in variants or candidate not in variants:
            raise ValueError("Comparison references unknown variant: " + repr(spec))
        pairs = []
        base_seeds = set(variants[base].get("seeds", seeds))
        candidate_seeds = set(variants[candidate].get("seeds", seeds))
        pair_seeds = sorted(base_seeds & candidate_seeds)
        if not pair_seeds:
            raise ValueError("Comparison has no predeclared common seed: " + repr(spec))
        for case in cases:
            for seed in pair_seeds:
                a, b = index.get((base, case, seed)), index.get((candidate, case, seed))
                valid = a is not None and b is not None and _valid(a) and _valid(b)
                row = dict(
                    comparison=spec["id"],
                    baseline=base,
                    candidate=candidate,
                    case=case,
                    day=day_by_case[case],
                    seed=seed,
                    complete=valid,
                    baseline_status=a.get("status") if a else "missing",
                    candidate_status=b.get("status") if b else "missing",
                )
                for name in METRICS:
                    row["baseline_" + name] = a.get("row", {}).get(name) if a else None
                    row["candidate_" + name] = b.get("row", {}).get(name) if b else None
                    row["delta_" + name] = (
                        b["row"][name] - a["row"][name]
                        if valid and (_number(a["row"].get(name)) and _number(b["row"].get(name)))
                        else None
                    )
                row["F_gain_percent"] = (
                    100 * (1 - b["row"]["F"] / a["row"]["F"])
                    if valid and a["row"]["F"] > 0
                    else None
                )
                pairs.append(row)
        complete = all(row["complete"] for row in pairs)
        date_rows = []
        for day in days:
            day_pairs = [row for row in pairs if row["day"] == day]
            day_complete = all(row["complete"] for row in day_pairs)
            case_means = []
            for case in {row["case"] for row in day_pairs}:
                own = [row for row in day_pairs if row["case"] == case]
                case_means.append(
                    {
                        name: _mean(row[name] for row in own)
                        for name in ("baseline_F", "candidate_F")
                    }
                    if all(row["complete"] for row in own)
                    else None
                )
            base_f = _mean(row["baseline_F"] for row in case_means) if day_complete else None
            candidate_f = _mean(row["candidate_F"] for row in case_means) if day_complete else None
            date_rows.append(
                dict(
                    day=day,
                    complete=day_complete,
                    baseline_F=base_f,
                    candidate_F=candidate_f,
                    F_gain_percent=100 * (1 - candidate_f / base_f)
                    if day_complete and base_f > 0
                    else None,
                    deltas={
                        name: _mean(
                            _mean(row["delta_" + name] for row in day_pairs if row["case"] == case)
                            for case in sorted({row["case"] for row in day_pairs})
                        )
                        if day_complete
                        and all(row["delta_" + name] is not None for row in day_pairs)
                        else None
                        for name in METRICS
                    },
                )
            )
        gains = [row["F_gain_percent"] for row in date_rows]
        scored = complete and all(value is not None for value in gains)
        comparisons.append(
            dict(
                **spec,
                complete=complete,
                status="complete" if complete else "incomplete",
                paired_seeds=pair_seeds,
                excluded_seeds=dict(
                    baseline=sorted(base_seeds - candidate_seeds),
                    candidate=sorted(candidate_seeds - base_seeds),
                ),
                expected_pairs=len(pairs),
                valid_pairs=sum(row["complete"] for row in pairs),
                dates=date_rows,
                mean_paired_F_gain_percent=_mean(gains) if scored else None,
                F_gain_date_bootstrap_95ci=bootstrap_ci(gains) if scored else None,
                wins=sum(value > 1e-10 for value in gains) if scored else None,
                ties=sum(abs(value) <= 1e-10 for value in gains) if scored else None,
                losses=sum(value < -1e-10 for value in gains) if scored else None,
            )
        )
        paired.extend(pairs)
    factorials = []
    budget_cells = {}
    adaptive_cells = {}
    for variant, config in variants.items():
        settings = config.get("overrides", {})
        if variant == "gate" or "budget" in config.get("group", ""):
            proxy = settings.get("proxy", 192)
            previews = settings.get("previews", 6)
            generations = settings.get("generations", 16)
            if generations == 16 and proxy in (96, 192) and previews in (3, 6):
                budget_cells[proxy, previews] = variant
        if "adapt" in config.get("group", ""):
            adaptation = config.get("adaptive", settings)
            mutation = adaptation.get("adaptive_mutation")
            crossover = adaptation.get("adaptive_crossover")
            if isinstance(mutation, bool) and isinstance(crossover, bool):
                adaptive_cells[int(mutation), int(crossover)] = variant
    for name, cells, xs, ys in (
        ("budget_2x2", budget_cells, [96, 192], [3, 6]),
        ("adaptive_2x2", adaptive_cells, [0, 1], [0, 1]),
    ):
        if len(cells) != 4:
            continue
        common_seeds = sorted(
            set.intersection(
                *(set(variants[variant].get("seeds", seeds)) for variant in cells.values())
            )
        )
        if not common_seeds:
            raise ValueError("Factorial comparison has no common planned seeds")
        records = []
        for (x, y), variant in sorted(cells.items()):
            selected = [index.get((variant, case, seed)) for case in cases for seed in common_seeds]
            complete = all(trial is not None and _valid(trial) for trial in selected)
            means = {}
            for metric in ("F", "cpu"):
                means[metric] = (
                    _mean(
                        _mean(
                            _mean(
                                index[variant, case, seed]["row"][metric] for seed in common_seeds
                            )
                            for case in cases
                            if day_by_case[case] == day
                        )
                        for day in days
                    )
                    if complete
                    else None
                )
            records.append(dict(x=x, y=y, variant=variant, complete=complete, means=means))
        factorials.append(
            dict(
                name=name,
                x_levels=xs,
                y_levels=ys,
                paired_seeds=common_seeds,
                cells=records,
                complete=all(row["complete"] for row in records),
            )
        )
    ranking_seeds = sorted(
        set.intersection(*(set(v.get("seeds", seeds)) for v in variants.values()))
    )
    if not ranking_seeds:
        raise ValueError("Global Pareto and weight comparisons need common planned seeds")
    for summary in summaries:
        summary["ranking_means"] = {
            metric: _mean(
                _mean(
                    _mean(
                        index[summary["variant"], case, seed]["row"][metric]
                        for seed in ranking_seeds
                    )
                    for case in cases
                    if day_by_case[case] == day
                )
                for day in days
            )
            if summary["complete"]
            else None
            for metric in ("F", "T", "R", "D", "cpu")
        }
    weight_rescore = []
    objective = plan.get("objective", {})
    horizon = objective.get("horizon_seconds", 900)
    fleet = objective.get("vehicles", plan.get("configuration", {}).get("vehicles", 6))
    speed = objective.get("speed_cells_per_second", 1)
    for label, weights in WEIGHTS:
        scores = []
        for summary in summaries:
            metrics = summary["ranking_means"]
            score = (
                sum(
                    w * metrics[name] / scale
                    for w, name, scale in zip(
                        weights, ("T", "R", "D"), (horizon, horizon, fleet * speed * horizon)
                    )
                )
                if summary["complete"]
                else None
            )
            scores.append(dict(variant=summary["variant"], score=score))
        ordered = sorted(
            (row for row in scores if row["score"] is not None), key=lambda r: r["score"]
        )
        for row in scores:
            row["rank"] = (
                1 + sum(other["score"] < row["score"] - 1e-12 for other in ordered)
                if row["score"] is not None
                else None
            )
        weight_rescore.append(dict(label=label, weights=list(weights), scores=scores))
    for summary in summaries:
        summary["pareto_efficient"] = summary["complete"] and not any(
            other["complete"]
            and other["ranking_means"]["F"] <= summary["ranking_means"]["F"]
            and other["ranking_means"]["cpu"] <= summary["ranking_means"]["cpu"]
            and (
                other["ranking_means"]["F"] < summary["ranking_means"]["F"]
                or other["ranking_means"]["cpu"] < summary["ranking_means"]["cpu"]
            )
            for other in summaries
        )
    return dict(
        schema="agv-sensitivity-analysis-v1",
        study_id=plan.get("study_id"),
        complete=all(row["complete"] for row in summaries) and not unexpected,
        analysis_unit="source date; seeds averaged within case, cases within date, then dates equally",
        uncertainty="Descriptive date bootstrap only; few dates, prior selection, no significance claim",
        baseline=plan.get("baseline", "gate"),
        case_count=len(cases),
        source_date_count=len(days),
        planned_trials=len(expected),
        observed_trials=len(trials),
        status_counts=dict(Counter(row.get("status", "missing_status") for row in trials)),
        missing_trials=missing,
        unexpected_trials=unexpected,
        trial_status=inventory,
        variants=summaries,
        comparisons=comparisons,
        paired=paired,
        factorials=factorials,
        ranking_seeds=ranking_seeds,
        weight_rescore=dict(
            reoptimized=False,
            interpretation="Same trajectories, alternative preference weights",
            scenarios=weight_rescore,
        ),
    )


def _csv(path, rows, fields=None):
    if fields is None:
        fields = list(rows[0]) if rows else ["status"]
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value, digits=4):
    return f"{value:.{digits}f}" if _number(value) else "—"


def _markdown(plan, result):
    display_comparisons = [row for row in result["comparisons"] if row.get("declared")]
    if not display_comparisons:
        display_comparisons = result["comparisons"]
    provenance = plan.get("case_provenance", {})
    unique_orders = (
        sum(provenance[case]["tasks"] for case in _case_ids(plan))
        if len(provenance) == result["case_count"]
        and result["source_date_count"] == result["case_count"]
        and all(_number(provenance[case].get("tasks")) for case in _case_ids(plan))
        else None
    )
    lines = [
        f"# 稳定性与敏感性实验：{result['study_id']}",
        "",
        f"计划{result['planned_trials']}次，已记录{result['observed_trials']}次；"
        f"{result['case_count']}个窗口、{result['source_date_count']}个来源日期。"
        f"状态：{'全部计划比较完整' if result['complete'] else 'incomplete：存在缺失或无效运行'}。",
        "",
        "先在同一窗口内平均随机seed，再在来源日期内平均窗口，最后对日期等权平均。"
        "seed重复不增加独立业务日期；日期bootstrap 95%区间仅作描述。"
        "四个或少量日期、既有数据复用与开发选择均不支持统计显著或普遍获益结论。",
        "",
        "本计划使用既有开发窗口，属于回顾性评价；本轮不据开发结果自动更换默认算法。",
        "",
        "失败和缺失运行计入计划总数；对应方案和比较标记incomplete，"
        "不使用成功子样本均值参与排名。aggregate.json保留全部运行状态和失败详情。",
        "",
        "## 同输入核心演进及资源消耗",
        "",
        "|方案|状态|有效/计划|F|T|R|D|CPU秒|日期内seed SD|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if unique_orders is not None:
        lines[4:4] = [
            f"本轮{result['planned_trials']}次方法/seed运行复用"
            f"{result['case_count']}个窗口，共{unique_orders}条唯一源请求；"
            f"独立业务场景仍为{result['source_date_count']}个来源日期。"
            "重复求解不增加唯一订单数或独立业务样本数。",
            "",
        ]
    for row in result["variants"]:
        m = row["means"]
        lines.append(
            f"|{row['variant']}|{row['status']}|{row['valid']}/{row['expected']}|"
            + "|".join(_fmt(m[name]) for name in ("F", "T", "R", "D", "cpu"))
            + f"|{_fmt(row['F_seed_sd_mean'])}|"
        )
    lines += [
        "",
        "CPU是模拟执行累计计算耗时，不是实际AGV物理时间或单次决策延迟；"
        "F/T/R/D仍按计划的统一目标与物理规则评价。不同历史模型或不同输入的绝对F不能直接横比。",
        "",
        "![Core metrics](figures/core_metrics.png)",
        "",
        "## 固定配对与逐日期差异",
        "",
        "改善率为每日期先分别平均同case/seed的F，再计算相对基线的下降百分比；"
        "正数表示候选F更低。pair键固定为case/seed，禁止按最佳seed选择。",
        "",
        "比较仅使用两组预声明seed的交集；交集在读取成绩前由计划确定。"
        "缺失/失败不会缩小该交集，其余seed仍完整保留在各方案稳定性统计。",
        "正文展示计划显式声明的比较；JSON和paired.csv另保留所有方案相对gate的完整配对。",
        "",
        "|比较|类型|配对seed|状态|有效/计划配对|平均F改善%|日期bootstrap 95%|胜/平/负日期|",
        "|---|---|---|---|---:|---:|---|---|",
    ]
    for row in display_comparisons:
        ci = row["F_gain_date_bootstrap_95ci"]
        interval = f"[{_fmt(ci[0])}, {_fmt(ci[1])}]" if ci else "—"
        counts = f"{row['wins']}/{row['ties']}/{row['losses']}" if row["complete"] else "—"
        lines.append(
            f"|{row['id']}|{row.get('label', row.get('kind', 'declared'))}|"
            f"{','.join(map(str, row['paired_seeds']))}|{row['status']}|"
            f"{row['valid_pairs']}/{row['expected_pairs']}|"
            f"{_fmt(row['mean_paired_F_gain_percent'])}|{interval}|{counts}|"
        )
    lines += [
        "",
        "|比较|来源日|状态|基线F|候选F|F改善%|ΔT|ΔR|ΔD|ΔCPU秒|",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for comparison in display_comparisons:
        for row in comparison["dates"]:
            lines.append(
                f"|{comparison['id']}|{row['day']}|"
                f"{'complete' if row['complete'] else 'incomplete'}|"
                + "|".join(
                    _fmt(row[name]) for name in ("baseline_F", "candidate_F", "F_gain_percent")
                )
                + "|"
                + "|".join(_fmt(row["deltas"][name]) for name in ("T", "R", "D", "cpu"))
                + "|"
            )
    lines += [
        "",
        "![Paired effects](figures/paired_effects.png)",
        "",
        "![Seed stability](figures/seed_stability.png)",
        "",
        "## 预算与参数敏感性",
        "",
        "proxy、完整preview和代数上限分别比较；2×2资源组合可观察代理预算与完整预演的交互。"
        "上限不一定用满，应结合实际搜索次数、独特代理评分、preview和上限触发次数解释。"
        "simple→wide同时调整多个预算，代表整组配置变化；单参数结论以计划中声明的固定对照为准。",
        "",
        "|方案|profile|组别|参数覆盖|searches|proxy|preview|proxy上限触发|preview上限触发|",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    configs = {row["id"]: row for row in plan["variants"]}
    for row in result["variants"]:
        search = row["search_totals"]
        config = configs[row["variant"]]
        overrides = json.dumps(
            {**config.get("overrides", {}), **config.get("adaptive", {})}, ensure_ascii=False
        )
        lines.append(
            f"|{row['variant']}|{row['profile']}|{row['group']}|{overrides}|"
            + "|".join(
                str(search[name])
                for name in (
                    "searches",
                    "proxy_evaluations",
                    "previews",
                    "proxy_cap_hits",
                    "preview_cap_hits",
                )
            )
            + "|"
        )
    lines += ["", "![Sensitivity](figures/sensitivity.png)"]
    lines += [
        "",
        "自适应四组固定同一移植后的GA实现及初始pm=0.7、pc=0.9，"
        "分别开关pm/pc自适应；11/00、10/00、01/00对应受控比较。"
        "wide_adapt11与原wide的差异还包含遗传算子实现和随机调用路径变化，"
        "是整组移植方案比较，不能把全部收益归因于自适应本身。",
    ]
    for factorial in result["factorials"]:
        lines += [
            "",
            f"![{factorial['name']}](figures/{factorial['name']}.png)",
            "",
            f"{factorial['name']}四格使用共同预声明seed={factorial['paired_seeds']}；"
            "每格均按同一日期等权汇总，避免默认方案较多seed造成比较样本不一致。",
        ]
    lines += [
        "",
        "## 成本与质量权衡",
        "",
        f"Pareto及权重排名统一使用所有方案预声明seed交集{result['ranking_seeds']}。"
        "Pareto图只在全部计划运行有效的方案上比较等权日期平均F与CPU；"
        "无法同时降低两者的方案并不因此无价值，取舍应结合业务目标。",
        "",
        "![Pareto](figures/pareto.png)",
        "",
        "## 权重重评分的稳健性",
        "",
        "以下对同一批已执行轨迹的T/R/D使用不同偏好权重重新计分，"
        "没有重新优化、重新训练或重跑调度。排名变化不能解释为算法适应了新权重。",
        "",
        "|权重(T/R/D)|方案|重评分|排名|",
        "|---|---|---:|---:|",
    ]
    for scenario in result["weight_rescore"]["scenarios"]:
        for row in scenario["scores"]:
            lines.append(
                f"|{'/'.join(map(str, scenario['weights']))}|{row['variant']}|"
                f"{_fmt(row['score'])}|{row['rank'] if row['rank'] is not None else '—'}|"
            )
    lines += [
        "",
        "![Weight rescore](figures/weight_rescore.png)",
        "",
        "## 解释边界与证据",
        "",
        "本轮评估seed主要检查随机搜索稳定性，不等同独立DQN训练seed。"
        "同一冻结模型多次推断不能证明学习过程稳定；训练稳定性需要从零初始化并重复训练。"
        "既有公开验证/测试日期重新使用时应标记回顾性评价，不能重新称作未见测试。",
        "",
        "真实订单流映射入本项目固定large、62×47网格、6车、5层仿真，"
        "不是原WEPA地图或原仓库整仓运行复刻；货位映射随机种子固定为17。"
        "原始WEPA订单用于重建这些固定窗口与初始库存，货架位置及单位时间运动仍是课程模型假设。"
        "不同seed和多轮运行复用相同源订单，不增加不同业务数据数量。"
        "旧DQN的30/60分钟窗口、训练过程及五日期成绩作为历史证据保存，"
        "不与本轮15分钟开发窗口的绝对F混成一个优劣排名；本轮自适应GA是同环境算子移植比较。",
        "",
        "输入计划、原始trials、汇总aggregate.json、summary.csv、paired.csv与figure文件分别保存；"
        "本报告器不修改输入、原源码或封存归档，不运行算法。"
        "任何负改善、超时或无效结果均原样保留。",
        "",
        "## 运行与核验",
        "",
        "在仓库根目录使用已准备好的虚拟环境。以下验证读取原始轨迹核对紧凑记录；"
        "报告目录必须尚不存在，已有报告不会被覆盖。",
        "",
        "```bash",
        "uv run python scripts/run_sensitivity_study.py verify results/wepa-dev-sensitivity-20261120 --traces",
        "uv run python scripts/report_sensitivity_study.py results/wepa-dev-sensitivity-20261120 --output runs/sensitivity-report-new",
        "```",
        "",
    ]
    if plan.get("limitations"):
        lines += ["计划声明的限制：", ""] + [f"- {item}" for item in plan["limitations"]] + [""]
    return "\n".join(lines)


def plot_figures(plan, result, directory):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.dpi": 180,
            "pdf.fonttype": 42,
        }
    )
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    summaries = result["variants"]
    core = [row for row in summaries if row["group"] in ("core", "evolution")]
    if not core:
        core = summaries[:7]

    def save(fig, name):
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            fig.savefig(directory / f"{name}.{suffix}", bbox_inches="tight")
        plt.close(fig)

    def bars(ax, rows, metric, title):
        good = [row for row in rows if row["means"][metric] is not None]
        ax.bar(range(len(good)), [row["means"][metric] for row in good], color="#397d9c")
        ax.set_xticks(range(len(good)), [row["variant"] for row in good], rotation=40, ha="right")
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.2)
        if len(good) != len(rows):
            ax.text(0.01, 0.99, "Incomplete variants excluded", va="top", transform=ax.transAxes)

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, (metric, title) in zip(
        axes.flat,
        (
            ("F", "Fixed objective F (lower is better)"),
            ("T", "Last order completion T (s)"),
            ("R", "Mean response R (s)"),
            ("D", "Total distance D (cells)"),
            ("cpu", "Cumulative CPU (s / window)"),
            ("p90", "P90 response (s)"),
        ),
    ):
        bars(ax, core, metric, title)
    save(fig, "core_metrics")
    comparisons = [row for row in result["comparisons"] if row.get("declared")]
    if not comparisons:
        comparisons = result["comparisons"]
    fig, ax = plt.subplots(figsize=(10, max(3, 0.35 * len(comparisons))))
    for position, row in enumerate(comparisons):
        mean, ci = row["mean_paired_F_gain_percent"], row["F_gain_date_bootstrap_95ci"]
        if mean is not None:
            ax.plot(mean, position, "o", color="#297b58")
            if ci:
                ax.plot(ci, [position, position], color="#297b58", linewidth=2)
            ax.scatter(
                [r["F_gain_percent"] for r in row["dates"]],
                [position] * len(row["dates"]),
                color="#9fbfc3",
                s=17,
                zorder=0,
            )
        else:
            ax.text(0, position, " incomplete", color="#9d392d")
    ax.set_yticks(range(len(comparisons)), [row["id"] for row in comparisons])
    ax.axvline(0, color="black", linewidth=0.7)
    ax.set_xlabel("Paired F improvement (%) | descriptive date-bootstrap 95% interval")
    save(fig, "paired_effects")
    fig, ax = plt.subplots(figsize=(11, 4))
    for position, row in enumerate(core):
        values = [
            case["F_seed_sd"]
            for day in row["dates"]
            for case in day["cases"]
            if case["F_seed_sd"] is not None
        ]
        if values:
            ax.scatter([position] * len(values), values, color="#397d9c", alpha=0.7)
            ax.plot(position, statistics.mean(values), "_", color="#a64432", markersize=15)
    ax.set_xticks(range(len(core)), [row["variant"] for row in core], rotation=30, ha="right")
    ax.set_ylabel("Within-case sample SD of F across seeds")
    ax.set_title("Repeated seeds measure solver stability; dates remain the data clusters")
    save(fig, "seed_stability")
    sensitivity = [row for row in summaries if row not in core]
    if not sensitivity:
        sensitivity = summaries
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    bars(axes[0], sensitivity, "F", "Budget / parameter sensitivity: F")
    bars(axes[1], sensitivity, "cpu", "Budget / parameter sensitivity: CPU")
    save(fig, "sensitivity")
    for factorial in result["factorials"]:
        fig, axes = plt.subplots(1, 2, figsize=(9, 4))
        xs, ys = factorial["x_levels"], factorial["y_levels"]
        for ax, metric in zip(axes, ("F", "cpu")):
            matrix = [
                [
                    next(
                        row["means"][metric]
                        for row in factorial["cells"]
                        if row["x"] == x and row["y"] == y
                    )
                    for x in xs
                ]
                for y in ys
            ]
            numeric = [
                [value if value is not None else float("nan") for value in row] for row in matrix
            ]
            valid_nums = [v for row in matrix for v in row if v is not None]
            vmin = min(valid_nums) if valid_nums else 0.0
            vmax = max(valid_nums) if valid_nums else 1.0
            span = (vmax - vmin) or 1.0
            ax.imshow(numeric, cmap="Blues", aspect="auto", vmin=vmin, vmax=vmax)
            for iy, row in enumerate(matrix):
                for ix, value in enumerate(row):
                    norm = ((value - vmin) / span) if value is not None else 0.0
                    txt_color = "white" if norm > 0.55 else "#0f172a"
                    ax.text(
                        ix,
                        iy,
                        _fmt(value),
                        ha="center",
                        va="center",
                        color=txt_color,
                        fontweight="bold",
                    )
            ax.set_xticks(range(2), xs)
            ax.set_yticks(range(2), ys)
            if factorial["name"] == "budget_2x2":
                ax.set(xlabel="Proxy cap (generations = 16)", ylabel="Full-preview cap")
            else:
                ax.set(
                    xlabel="Adaptive mutation (0 = off, 1 = on)",
                    ylabel="Adaptive crossover (0 = off, 1 = on)",
                )
            ax.set_title(f"{metric} | common seeds {factorial['paired_seeds']}")
        save(fig, factorial["name"])
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    complete_rows = [row for row in summaries if row["complete"]]
    pareto_pts = sorted(
        (
            (row["ranking_means"]["cpu"], row["ranking_means"]["F"])
            for row in complete_rows
            if row["pareto_efficient"]
        ),
        key=lambda pt: pt[0],
    )
    if len(pareto_pts) >= 2:
        ax.plot(
            [p[0] for p in pareto_pts],
            [p[1] for p in pareto_pts],
            linestyle="--",
            color="#297b58",
            alpha=0.45,
            linewidth=1.1,
            zorder=1,
        )
    # Explicit collision-free label placements for dense CPU 13-15s cluster
    label_offsets = {
        "fcfs": ((8, 2), "left"),
        "eta": ((8, 2), "left"),
        "hungarian": ((8, 2), "left"),
        "simple": ((8, 3), "left"),
        "gate_proxy96_preview3": ((8, 6), "left"),
        "gate_preview3": ((8, -16), "left"),
        "gate_gen8": ((-10, 6), "right"),
        "gate_proxy96": ((-10, 8), "right"),
        "wide_adapt11": ((12, 16), "left"),
        "wide_adapt00": ((-14, -15), "right"),
        "wide_adapt10": ((12, -2), "left"),
        "wide": ((12, 9), "left"),
        "wide_adapt01": ((12, -13), "left"),
        "gate": ((-12, 2), "right"),
        "hga": ((-10, -10), "right"),
    }
    for row in complete_rows:
        cx, cy = row["ranking_means"]["cpu"], row["ranking_means"]["F"]
        ax.scatter(
            cx,
            cy,
            color="#297b58" if row["pareto_efficient"] else "#7994a1",
            s=46,
            zorder=3,
        )
        offset, ha = label_offsets.get(row["variant"], ((6, 4), "left"))
        use_arrow = abs(offset[0]) >= 10 or abs(offset[1]) >= 10
        ax.annotate(
            row["variant"],
            (cx, cy),
            xytext=offset,
            textcoords="offset points",
            fontsize=8.2,
            ha=ha,
            va="center",
            color="#0f172a",
            arrowprops=(
                dict(arrowstyle="-", color="#94a3b8", lw=0.75, shrinkA=0, shrinkB=3)
                if use_arrow
                else None
            ),
        )
    if complete_rows:
        xs = [r["ranking_means"]["cpu"] for r in complete_rows]
        ys = [r["ranking_means"]["F"] for r in complete_rows]
        ax.set_xlim(min(0.0, min(xs)) - 0.4, max(xs) + 3.2)
        yspan = (max(ys) - min(ys)) or 0.01
        ax.set_ylim(min(ys) - yspan * 0.14, max(ys) + yspan * 0.10)
    ax.grid(alpha=0.18)
    ax.set(
        xlabel="Mean cumulative CPU (s / window)",
        ylabel="Mean F (lower is better)",
        title="Quality / computation Pareto view (green = nondominated)",
    )
    save(fig, "pareto")
    scenarios = result["weight_rescore"]["scenarios"]
    fig, ax = plt.subplots(figsize=(9, 5))
    for row in core:
        ranks = [
            next(
                score["rank"] for score in scenario["scores"] if score["variant"] == row["variant"]
            )
            for scenario in scenarios
        ]
        if all(rank is not None for rank in ranks):
            ax.plot(range(len(scenarios)), ranks, "o-", label=row["variant"])
    ax.set_xticks(range(len(scenarios)), [row["label"] for row in scenarios])
    ax.set_ylabel("Rank after rescoring the same trajectories")
    ax.invert_yaxis()
    ax.set_title("Preference robustness only: no reoptimization or retraining")
    if ax.lines:
        ax.legend(loc="best", fontsize=8)
    save(fig, "weight_rescore")


def write_report(study, output=None):
    study = Path(study).resolve()
    output = Path(output).resolve() if output else study / "report"
    if output.exists():
        raise FileExistsError("Refuse to overwrite report directory: " + str(output))
    plan, trials = load_trials(study)
    result = analyze(plan, trials)
    inputs = [study / "plan.json", *sorted((study / "trials").glob("*.json"))]
    result["input_sha256"] = {
        str(path.relative_to(study)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in inputs
    }
    result["reporter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    (output / "aggregate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    rows = []
    for summary in result["variants"]:
        row = {
            key: summary[key]
            for key in (
                "variant",
                "profile",
                "group",
                "status",
                "expected",
                "observed",
                "valid",
                "failed",
                "missing",
            )
        }
        row.update(
            summary["means"],
            F_date_sd=summary["F_date_sd"],
            F_seed_sd_mean=summary["F_seed_sd_mean"],
            F_date_bootstrap_95ci=json.dumps(summary["F_date_bootstrap_95ci"]),
            pareto_efficient=summary["pareto_efficient"],
            ranking_seeds=json.dumps(result["ranking_seeds"]),
            ranking_F=summary["ranking_means"]["F"],
            ranking_cpu=summary["ranking_means"]["cpu"],
        )
        rows.append(row)
    _csv(output / "summary.csv", rows)
    _csv(output / "paired.csv", result["paired"])
    plot_figures(plan, result, output / "figures")
    (output / "中文实验报告.md").write_text(_markdown(plan, result), encoding="utf-8")
    if any(
        hashlib.sha256(path.read_bytes()).hexdigest() != digest
        for relative, digest in result["input_sha256"].items()
        for path in [study / relative]
    ):
        raise ValueError("Study evidence changed during report generation")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path, help="Directory containing plan.json and trials/*.json")
    parser.add_argument("--output", type=Path, help="New report directory (default: STUDY/report)")
    args = parser.parse_args()
    result = write_report(args.study, args.output)
    print(
        json.dumps(
            {
                "study_id": result["study_id"],
                "complete": result["complete"],
                "planned_trials": result["planned_trials"],
                "observed_trials": result["observed_trials"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
