"""Check the archived course-report runs and recompute paired improvements."""

import csv
import json
from math import isclose
from pathlib import Path
from statistics import mean

from cases import MAIN, SIZES, SUPPLEMENT

FORMAL = Path(__file__).resolve().parents[2] / "results" / "summary_tables" / "01_正式实验"


def read_csv(name):
    with (FORMAL / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    groups = {1: MAIN, 2: SUPPLEMENT, 3: SIZES}
    inputs = {
        (group, int(case.removeprefix("day").removeprefix("size"))): (
            value if group == 3 else value[2] + value[3]
        )
        for group, cases in groups.items() for case, value in cases.items()
    }
    rows = read_csv("03_逐次实验结果.csv")
    scores = {}
    totals = 0
    for row in rows:
        group, case, method, seed = (int(row[name]) for name in (
            "实验组编号", "案例编号", "方案编号", "随机种子"
        ))
        key = (group, case, method, seed)
        require(key not in scores, f"Duplicate run: {key}")
        count = int(row["订单数"])
        require(count == inputs[group, case], f"Order count differs: {key}")
        score, end, response, distance = (float(row[name]) for name in (
            "综合代价_F", "末单完成时间_T_秒", "平均响应时间_R_秒", "总移动距离_D_格"
        ))
        expected = (0.5 * end + 0.3 * response) / 900 + 0.2 * distance / 5400
        require(isclose(score, expected, rel_tol=1e-10), f"Invalid F: {key}")
        scores[key] = score
        totals += count
    expected_keys = {(group, case, method, seed) for group, case in inputs
                     for method in range(1, 8) for seed in range(3)}
    require(scores.keys() == expected_keys, "The 14×7×3 run matrix is incomplete")
    require(totals == 18354, "The total transported order count differs")

    summary = read_csv("01_七方案汇总.csv")
    require(len(summary) == 21, "Expected 21 summary rows")
    seen = set()
    for row in summary:
        group, method = int(row["实验组编号"]), int(row["方案编号"])
        require((group, method) not in seen, "Duplicate group or method summary")
        seen.add((group, method))
        matching = [v for (g, _, m, _), v in scores.items() if g == group and m == method]
        require(len(matching) == int(row["运行次数"]), "Run count differs from the summary")
        require(isclose(mean(matching), float(row["综合代价_F_均值"]), rel_tol=1e-10),
                "Mean F differs from the summary")

    plan_rows = read_csv("04_反事实规划记录.csv")
    plan_keys = {(int(r["实验组编号"]), int(r["案例编号"]), int(r["随机种子"])) for r in plan_rows}
    require(len(plan_rows) == len(plan_keys) and plan_keys == {
        (group, case, seed) for group, case in inputs for seed in range(3)
    }, "The counterfactual summary does not cover all 42 runs")

    def paired(group, candidate, reference):
        return 100 * mean(1 - scores[g, case, candidate, seed] / score
                          for (g, case, method, seed), score in sorted(scores.items())
                          if g == group and method == reference)

    print(json.dumps({"runs": len(scores), "orders": totals, "planning_rows": len(plan_rows),
                      "improvement_pct": {
                          group: {"joint_vs_GA": paired(group, 6, 3),
                                  "counterfactual_vs_GA": paired(group, 7, 3),
                                  "counterfactual_vs_joint": paired(group, 7, 6)}
                          for group in groups}}, indent=2))


if __name__ == "__main__":
    main()
