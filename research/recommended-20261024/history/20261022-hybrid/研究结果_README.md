# AGV 调度与混合路径算法研究包（2026-10-22）

本阶段完整可运行源码归档于 `../archives/Selected_20261022_source_and_evidence.tar.gz`（解压后位于 `agv_research/`，包含 `src/agv`、`scripts`、`tests`、`docs` 与 `results`）。

本轮系统实现并对比了 7 类订单调度策略与 6 种路径方案。在主确认 48 场景上，表现较优的候选配置为：静态场景采用 `Portfolio + 订单/车辆联合邻域`，动态场景采用 `Portfolio 锚点 + 蚁群订单搜索`，底层路径均采用 SIPP；路径层的蚁群/粒子群混合方案未带来稳定收益。

| 配置 | 主确认 48 场景 F 平均下降 | 额外 16 场景 F 平均下降 |
|---|---:|---:|
| 统一联合邻域＋SIPP | 0.6947% | 0.4562% |
| 分场景调度＋SIPP | 0.8945% | 0.3496% |

下降幅度均以同场景的上一轮 `Portfolio + SIPP` 为参照。分场景候选在主确认集上的平均 F 为 `0.894603`（参照组 `0.902909`），其中 `0.8945%` 为逐场景相对下降率的均值；主确认 48 场景中 27 个改善、21 个持平，95% 种子簇 Bootstrap 区间为 `[0.6409%, 1.1832%]`，累计 CPU 开销约为参照组的 `1.95` 倍。

在额外种子验证中，动态蚁群在 1/8 场景上相对统一方案略高，两种方案各有适用特点。在小规模精确参照上，8 个双车三订单实例均达到已证最优。本阶段评价公式固定为 `F = 0.5*T/Tref + 0.3*R/Rref + 0.2*D/Dref`。

## 相关文件

- 同目录数据表：[方案汇总.csv](方案汇总.csv)、[逐场景确认结果.csv](逐场景确认结果.csv)
- 归档 `Selected_20261022_source_and_evidence.tar.gz` 内包含：`agv_research/docs/`（实验报告、调度与路径接口说明、文献依据）及 `agv_research/results/path-study-20261022/`（推荐配置、统一对照配置与核验记录）

## 运行示例（解压归档后）

在 Python 3.10 及以上环境中：

```powershell
cd agv_research
$env:PYTHONPATH="$PWD/src"
python scripts/run_path_research.py --selection results/path-study-20261022/recommendation.json --regime static --output runs/static-demo.json
python scripts/run_path_research.py --selection results/path-study-20261022/recommendation.json --regime dynamic --output runs/dynamic-demo.json
```

切换统一对照方案时将 `--selection` 参数改为 `unified-control.json`，输出路径须使用新文件名。

## 核验与归档范围

373 项本地测试、205 份 Python 源码静态检查、架构边界检查、8 项网页接口契约与独立 wheel 安装运行均已通过；原评价器、独立验解器与仓库规则保持不变，12 份接口整理前后轨迹完全一致，518 条统计记录 F 复算一致。归档中完整保存开发、确认、额外种子、消融、同到达流对照、小规模最优证书、压力测试及实验负例。
