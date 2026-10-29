"""Re-audit historical anchor regressions and plot their first dispatch divergence."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from agv.core.objectives import LinearObjective
from agv.data.wepa import build
from agv.evaluation.objectives.linear_f import checked_score
from agv.experiments.cache import cache_key


def dispatch_difference(a, b):
    decisions = [{row["time"]: row["pairs"] for row in r["decisions"]} for r in (a, b)]
    return next(
        (
            t
            for t in sorted(set(decisions[0]) | set(decisions[1]))
            if decisions[0].get(t) != decisions[1].get(t)
        ),
        None,
    )


def physical_difference(a, b):
    return next(
        (
            t
            for t in range(min(a["time"], b["time"]) + 1)
            if any(x[t] != y[t] for x, y in zip(a["paths"], b["paths"]))
        ),
        None,
    )


def search_difference(a, b):
    logs = [{row["time"]: row for row in r["search_log"]} for r in (a, b)]
    return next(
        (
            t
            for t in sorted(set(logs[0]) & set(logs[1]))
            if logs[0][t].get("score") != logs[1][t].get("score")
        ),
        None,
    )


def searches(result, start):
    output = []
    for log in [row for row in result["search_log"] if row["time"] >= start][:3]:
        score = log.get("score")
        candidates = [
            dict(kind=c["kind"], predicted_F=c["score"]) for c in log.get("candidates", [])
        ]
        winners = [
            c["kind"]
            for c in candidates
            if c["predicted_F"] is not None
            and score is not None
            and math.isclose(c["predicted_F"], score, abs_tol=1e-12, rel_tol=0)
        ]
        output.append(
            dict(
                time=log["time"],
                optimizer=log.get("optimizer", log.get("mode")),
                base_score=log.get("base_score"),
                predicted_F=score,
                changed=log.get("changed", False),
                selected_kind=winners[0] if log.get("changed") and winners else "baseline",
                candidates=candidates,
                positions=[path[log["time"]] for path in result["paths"]],
                dispatches=[d["pairs"] for d in result["decisions"] if d["time"] == log["time"]],
            )
        )
    return output


def plot(scene, results, entry, target):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    start = entry["first_dispatch_divergence"]
    grid = [[int((x, y) in scene.blocked) for x in range(scene.width)] for y in range(scene.height)]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), layout="constrained")
    for axis, (method, result) in zip(axes, results.items()):
        axis.imshow(
            grid, cmap=ListedColormap(["#fbfbfb", "#d5d9df"]), origin="upper", vmin=0, vmax=1
        )
        for vehicle, path in enumerate(result["paths"]):
            segment = path[start : min(start + 61, len(path))]
            xs, ys = zip(*segment)
            color = f"C{vehicle}"
            axis.plot(xs, ys, color=color, linewidth=1.8, alpha=0.85, label=f"V{vehicle}")
            axis.scatter(xs[0], ys[0], color=color, s=42, edgecolors="white", zorder=3)
            axis.scatter(xs[-1], ys[-1], color=color, marker="x", s=26, zorder=3)
            axis.annotate(
                f"V{vehicle}",
                (xs[0], ys[0]),
                xytext=(3, 4),
                textcoords="offset points",
                fontsize=8,
                color=color,
            )
        axis.set(
            title=f"{method} | final F={entry['actual'][method]['F']:.6f}",
            xlabel="x / cells",
            ylabel="y / cells",
        )
        axis.set_xlim(-0.5, scene.width - 0.5)
        axis.set_ylim(scene.height - 0.5, -0.5)
        axis.legend(loc="upper right", ncol=3, fontsize=8)
    fig.suptitle(
        f"{entry['case']} | t={start}..{start + 60} | dots: initial positions; x: end of segment"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root", type=Path, default=Path("runs/wepa-optimization-20261028/pool-final")
    )
    parser.add_argument(
        "--protocol", type=Path, default=Path("protocols/wepa-20261029-frozen.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/review2-20261029/anchor-regressions.json")
    )
    parser.add_argument("--doc", type=Path, default=Path("docs/experiments/anchor-regressions.md"))
    parser.add_argument("--asset-dir", type=Path, default=Path("docs/experiments/assets"))
    args = parser.parse_args()
    frozen = json.loads(args.protocol.read_text())
    assert frozen["protocol_sha256"] == cache_key(
        {k: v for k, v in frozen.items() if k != "protocol_sha256"}
    )
    config = frozen["config"]
    objective = LinearObjective(**config["objective"])
    entries = []
    for phase in ("development", "validation"):
        aggregate = json.loads((args.input_root / phase / "runs.json").read_text())
        assert aggregate["complete"] and aggregate["protocol_sha256"] == frozen["protocol_sha256"]
        rows = {(r["case"], r["profile"], r["seed"]): r for r in aggregate["rows"]}
        for name in config[phase]:
            control, candidate = (rows[name, method, 0] for method in ("gate", "gate_anchor"))
            if candidate["F"] <= control["F"] + 1e-12:
                continue
            results, identities, actual = {}, {}, {}
            case = next(c for c in config["cases"] if c["case"] == name)
            model = build(case, **config["configuration"])
            for method in ("gate", "gate_anchor"):
                path = args.input_root / phase / f"{name}--{method}--s0.json"
                data = path.read_bytes()
                trace = json.loads(data)
                assert trace["case"] == case and trace["objective_id"] == frozen["objective_id"]
                assert trace["implementation_sha256"] == frozen["sources"]
                assert trace["protocol_sha256"] == frozen["protocol_sha256"]
                assert trace["row"]["profile"] == method and trace["row"]["seed"] == 0
                aggregate_row = rows[name, method, 0]
                assert all(trace["row"][key] == aggregate_row[key] for key in trace["row"])
                result = trace["result"]
                scoring = checked_score(model, result, objective)
                assert math.isclose(
                    scoring["F_linear_v2"], trace["row"]["F"], abs_tol=1e-12, rel_tol=0
                )
                assert all(result[key] == trace["row"][key] for key in ("T", "R", "D"))
                results[method] = result
                identities[method] = dict(
                    file=path.name,
                    sha256=hashlib.sha256(data).hexdigest(),
                    independent_audit=scoring["audit"],
                )
                actual[method] = {key: trace["row"][key] for key in ("F", "T", "R", "D", "p90")}
            a, b = results.values()
            dispatch = dispatch_difference(a, b)
            physical = physical_difference(a, b)
            policy = search_difference(a, b)
            assert policy is not None and dispatch is not None and physical is not None
            assert policy <= dispatch <= physical
            first = next(log for log in b["search_log"] if log["time"] == policy)
            assert first["score"] < first["base_score"] - 1e-12
            entry = dict(
                case=name,
                split=phase,
                first_policy_score_divergence=policy,
                first_dispatch_divergence=dispatch,
                first_physical_divergence=physical,
                classification="b-consistent; causal mechanism not established",
                strict_prediction_improvement=first["base_score"] - first["score"],
                future_unreleased_tasks_at_policy_divergence=sum(
                    j["release"] > policy for j in case["tasks"]
                ),
                actual=actual,
                delta={
                    key: actual["gate_anchor"][key] - actual["gate"][key] for key in actual["gate"]
                },
                traces=identities,
                next_three_searches={
                    method: searches(result, policy) for method, result in results.items()
                },
                next_three_tasks_per_vehicle={
                    method: {
                        str(k): [
                            r["task"]
                            for r in result["records"]
                            if r["vehicle"] == k and r["assigned_at"] >= dispatch
                        ][:3]
                        for k in range(model["vehicles"])
                    }
                    for method, result in results.items()
                },
            )
            if policy != dispatch:
                entry["next_three_searches_after_dispatch"] = {
                    method: searches(result, dispatch) for method, result in results.items()
                }
            target = args.asset_dir / f"anchor-regression-{name}.png"
            entry["plot"] = target.as_posix()
            plot(model["scene"], results, entry, target)
            entries.append(entry)
    assert len(entries) == 5 and sum(e["split"] == "development" for e in entries) == 3
    report = dict(
        schema="agv-anchor-regressions-v1",
        historical_measurement_snapshot="ccff577",
        protocol_sha256=frozen["protocol_sha256"],
        objective_id=frozen["objective_id"],
        independently_audited_runs=2 * len(entries),
        source_resigned=False,
        sealed_results_read=False,
        limitation="Saved predictions are complete SIPP rollouts of currently visible tasks, not raw GA proxy estimates. Comparing them to the whole-window result cannot identify proxy estimation error. No frozen-plan counterfactual or causal intervention was executed.",
        entries=entries,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_doc(args.doc, entries, args.output)
    print(
        json.dumps(
            dict(regressions=len(entries), independently_audited_runs=10, output=str(args.output))
        )
    )


def write_doc(path, entries, evidence):
    lines = [
        "# gate_anchor 五个回退窗口的轨迹诊断",
        "",
        "本次重读 `ccff577` 冻结协议下的原始轨迹，对开发集 3 个、验证集 2 个回退窗口的两种方案共 10 次运行重新独立验解和计分。没有重跑或重签历史算法测量，也没有读取旧封存集。",
        "",
        "五例都在更低的可见任务 SIPP 预测分数被采纳后出现整窗回退；第一处分叉处的分数差严格大于数值容差，因此没有证据把它们归因于平局顺序。日志没有保存原始 GA 代理估价，不能据此确认代理误差占多数。下文统一标为 **b-consistent（与滚动决策的连锁效应一致）**，不把相关性当成因果证明。",
        "",
        "预测 F 针对当时已发布的任务，实际 F 针对整窗最终执行；即使此刻已经没有后续订单，后续搜索和逐批提交也会改变预演的完整计划。两者相减不能直接解释为代理误差。要区分代理误差与执行连锁，需要另做冻结计划执行和候选互换的反事实实验。",
        "",
        "| 窗口 | 集合 | 预测首次分叉 | 派单首次分叉 | 路径首次分叉 | 最终 ΔF | ΔT | ΔR | ΔD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for e in entries:
        d = e["delta"]
        lines.append(
            f"| {e['case']} | {e['split']} | {e['first_policy_score_divergence']} | {e['first_dispatch_divergence']} | {e['first_physical_divergence']} | {d['F']:+.6f} | {d['T']:+g} | {d['R']:+.3f} | {d['D']:+g} |"
        )
    for e in entries:
        lines.extend(
            [
                "",
                f"## {e['case']}",
                "",
                f"第一处分数差发生于 t={e['first_policy_score_divergence']}，anchor 相对其基准预演改善 {e['strict_prediction_improvement']:.9f}；当时尚未发布任务 {e['future_unreleased_tasks_at_policy_divergence']} 个。派单在 t={e['first_dispatch_divergence']} 分叉，物理位置在 t={e['first_physical_divergence']} 分叉。分类：b-consistent；未做因果干预。",
                "",
                "| 策略 | 实际 F | T | R | D | P90 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for method, values in e["actual"].items():
            lines.append(
                f"| {method} | {values['F']:.9f} | {values['T']} | {values['R']:.3f} | {values['D']} | {values['p90']} |"
            )
        lines.extend(
            [
                "",
                "分数首次分叉起的三次搜索如下。`baseline` 表示该次保留基准；`null` 分数表示候选被剪枝或没有完整评分，不表示零成本。车辆位置、候选评分和每辆车随后三个真实任务的完整紧凑记录见配套 JSON。",
                "",
                "| 策略 | t | base_score | 选中预测 F | 选中来源 | 当步实际派单 |",
                "|---|---:|---:|---:|---|---|",
            ]
        )
        for method, searches_ in e["next_three_searches"].items():
            for search in searches_:

                def fmt(value):
                    return "—" if value is None else f"{value:.9f}"

                lines.append(
                    f"| {method} | {search['time']} | {fmt(search['base_score'])} | {fmt(search['predicted_F'])} | {search['selected_kind']} | {search['dispatches']} |"
                )
        plot_path = Path(e["plot"]).relative_to(path.parent).as_posix()
        lines.extend(
            [
                "",
                f"![{e['case']} first dispatch divergence]({plot_path})",
                "",
                "图中两栏采用同一地图和时间窗；圆点为派单首次分叉时的位置，叉号为随后 60 步末的位置，线条为实际执行轨迹。",
            ]
        )
    lines.extend(
        [
            "",
            "## 结论与后续决策",
            "",
            "五例首次预测分叉时都尚未正式闭流，而且确实还存在未发布任务（分别为 1、1、25、1、18 个）。因此可优先检验闭流后才启用 anchor 的假设，但这不是该规则有效的证明。正式闭流时间、已发布任务数和实际后续重规划属于不同状态。任何新触发规则都应在新的开发日期上预先定义，并在独立日期验证，不能用这五个回退窗口反复选规则。",
            "",
            "当前没有证据要求修改平局规则，也没有证据证明 A3 代理校正会消除这些回退。默认策略仍保留 gate。",
            "",
            f"结构化证据：[{evidence.name}](../../{evidence.as_posix()})。复查脚本为 `scripts/analyze_anchor_regressions.py`，需要原始本地轨迹目录与可选 `plots` 依赖。公开仓库保留紧凑审计记录和五张图，未上传完整运行轨迹。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
