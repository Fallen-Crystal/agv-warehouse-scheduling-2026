# Warehouse AGV Scheduling（仓库穿梭无人车智能调度）

面向多取货任务并发场景的 AGV 调度、离散时空仿真与独立验解平台。核心仅依赖 Python 3.10+ 标准库，提供命令行、本地网页回放和可复现的多 seed 对照实验。

## 1. 快速开始

```bash
uv sync --extra dev
uv run agv serve                      # 本地网页（仅绑定 127.0.0.1）
uv run agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 \
  --algorithm bcrd_budget --output runs/v4-bcrd.json
uv run python research/recommended-20261024/current/run.py \
  --case wepa-day45-bin4335 --seed 0 --output runs/wepa-demo.json
```

输出文件已存在时默认拒绝覆盖，需要覆盖时加 `--overwrite`。更多命令与复现流程见 [docs/usage.md](docs/usage.md)。

## 2. 两条研究主线

| 主线 | 场景 | 代码入口 | 目标函数 |
|---|---|---|---|
| A 自研通用引擎 | 合成栅格、V4 分层货架、V9/V9.1 混合货架 | `src/agv/`（CLI `agv`） | $F=0.5\,T/T_{\text{ref}}+0.3\,R/R_{\text{ref}}+0.2\,D/D_{\text{ref}}$，以同场景 `baseline` 为参照 |
| B WEPA 真实订单流 | 62×47 网格、6 车、5 层、900 秒窗口 | `research/recommended-20261024/` | $F=0.5\,T/900+0.3\,R/900+0.2\,D/5400$ |

- **T**：最后一单完成时刻（主线 B 不含最终返库）；**R**：订单平均发布到完成耗时；**D**：总行驶里程（含最终返库）。F 越低越好。
- 两条主线以及不同协议、不同窗口长度之间的绝对 F 不可比。
- **改善率约定**：全仓库百分比均为“改善率”，正数 = 目标值降低 = 更好。

## 3. 方案名速查

| 名称 | 主线 | 含义 | 相对上一版的变化 |
|---|---|---|---|
| `baseline` | A | 距离贪心派单 + 时空 A* | — |
| `joint_only` / `joint_batch` | A | LNS 联合重规划 / 静态首轮批次滚动 | 冲突车辆联合重排 |
| `sipp_budget` | A | SIPP 安全区间规划 + 拥堵关联修复，每次最多试 6 个候选 | 规划器换 SIPP，加候选预算 |
| `sipp_batch` | A | 静态场景下对首轮分配做批次滚动筛选 | 仅静态模式 |
| `bcrd_budget` | A | 高积压时在影子环境中试派候选批次序列 | 新增影子试派 |
| `sipp_stream_bcrd` | A | V9.1 混合背靠背货架流式派单 + BCRD 批滚动 | 适配 V9.1 流式关闭规则 |
| `fcfs` / `eta` | B | 先到先服务 / 最早到达优先 | 规则基线 |
| `hungarian` | B | 匈牙利算法局部匹配 | 一次性局部最优匹配 |
| `simple` → `wide` | B | 遗传算法派单；`wide` 扩大种群与代数预算 | 预算整体扩大 |
| `gate` | B | `wide` + 事件门控（仅必要时触发 GA）+ SIPP 预演 | 减少触发次数（推荐默认） |
| `hga` | B | 以匈牙利解初始化的 GA | 更改初始化方式 |
| `*_preview3` / `*_gen8` / `*_gen24` | B | 预演次数降为 3 / 代数降为 8 / 代数扩至 24 | 预算对照 |
| `wide_adaptXY` | B | `X`=变异率自适应开关，`Y`=交叉率自适应开关 | 算子对照 |
| `dqn-experiment-v2` | B | 自适应 GA 算子 + Double DQN 双动作选择 | 已归档（相对纯自适应 GA −0.37%，见 [说明](research/dqn-experiment-v2/README.md)） |

## 4. 主要结论（截至 2026-11-21）

**主线 B（WEPA 真实订单流）**

1. GA 类方案在 4 个既有验证窗口上全部优于规则基线：`gate` 相对 `fcfs` 改善 +5.45%、相对 `eta` 改善 +2.43%、相对 `hungarian` 改善 +3.87%，4 个日期全部改善（4/0/0）。
2. `gate` 与 `wide` 没有可分辨差异（既有验证窗口 −0.10%，0/2/2；开发窗口 +0.11%，1/3/0）。默认方案保留 `gate`，理由是开发集触发 GA 搜索次数减少 63%（205 vs 560 次），且延续 2026-10 选型口径。
3. 开发集最优的 `hga`（相对 `gate` +0.95%，2/1/1）在既有验证窗口全部变差（−1.12%，0/0/4），不采用；组合方案 `hga_adapt01` 相对 `hga` 改善 +0.79%（3/0/1），但仍差于 `gate`（−0.28%，2/0/2）。
4. 扩大预算没有收益：24 代（`gate_gen24`）比默认差 −1.41%（0/0/4），说明默认代数不是瓶颈。缩小预演可省资源：`gate_preview3` CPU 降低约 44%（验证集 21.66→12.09 秒），F 变差 −0.33%（0/2/2），适合算力受限时使用。
5. 自适应算子结论不稳定：只开交叉自适应（`wide_adapt01` vs `wide_adapt00`）在开发集改善 +0.94%（3/1/0），在既有验证窗口变差 −0.54%（1/0/3）。开启变异自适应时超 86% 代数触及 0.95 上限（开发集 `wide_adapt10` 4,639/5,376 代、`wide_adapt11` 4,640/5,360 代）。

**主线 A（自研通用引擎）**

1. V4 动态场景：`bcrd_budget` 的 F 改善 +3.01%（0.9699±0.0191），CPU 0.17 秒，为该场景推荐方案。
2. Legacy 静态场景：`sipp_batch` 平均流程时间改善 +2.62%、总移动步数减少 4.24%，代价是 CPU 约为 `baseline` 的 130 倍（0.08→10.27 秒）。
3. Legacy 动态与 V9.1 动态场景：Legacy 动态同 seed 配对虽全胜 `baseline`（+3.39%，5/0/0），但跨场景 seed 标准差（±3）远大于各 SIPP 变体间差异（<0.15）；V9.1 动态下除 `sipp_stream_matching` 外其余方案与 `baseline` 完全相同，未产生收益。
4. V9.1 静态场景与参数扫描：`max_batches` 从 1 增至 2 使 F 改善约 +1.53%，再增至 4/6 结果完全相同，取 2 即可；`trial_budget` 在 2–10 内几乎无影响（`b2` 最省时）。

**局限**：主线 B 只有 4 个来源日期，结论为描述性，未做统计显著性检验；4 个验证窗口已在 2026-10 用于选型（当时 `gate` 单 seed 0 为 0.896406，本轮 seed 0–2 均值为 0.899159，口径不同不矛盾），本轮属回顾性复评。仿真中货位映射、层数与运动速率均为课程模型假设。

## 5. 实验索引与总结报告

- **团队全链路梳理与实验总结 PDF**：[results/AGV仓库梳理与实验总结报告.pdf](results/AGV仓库梳理与实验总结报告.pdf)
- **全部现行与历史实验索引**：[results/README.md](results/README.md)

| 实验 ID | 主线 | 内容 | 运行数 | 报告 |
|---|---|---|---:|---|
| `wepa-dev-sensitivity-20261120` | B | 开发窗口：方案演进 + 预算 2×2 + 自适应 2×2 | 200 | [REPORT.md](results/wepa-dev-sensitivity-20261120/REPORT.md) |
| `wepa-val-sensitivity-20261121` | B | 既有验证窗口回顾性复评 + 扩大预算与组合方案 | 156 | [REPORT.md](results/wepa-val-sensitivity-20261121/REPORT.md) |
| `core-sensitivity-20261121` | A | Legacy / V4 / V9.1 演进 + 参数扫描（5 seeds） | 205 | [REPORT.md](results/core-sensitivity-20261121/REPORT.md) |

全部运行均通过独立物理验解。

## 6. 项目结构（当前架构 v0.6.0）

当前主线 A 为 `src/agv/` 模块化架构，主线 B 通过 `research/recommended-20261024/current/run.py` 独立运行（尚未并入 `agv` CLI）：

```text
src/agv/
  domain.py        Task / Scenario 数据模型、坐标校验与示例生成
  warehouse/       V4 / V9 / V9.1 分层与混合货架几何与层序约束
  simulation.py    唯一真实执行状态机、预约更新与重规划全未来审计
  planning/        时空 A*、SIPP 安全区间规划、增量预约索引、几何缓存、LNS 联合修复
  dispatch/        贪心 / 批量匹配 / 定位 / 流式派单 / BCRD 影子滚动 / 静态批规划 / 注册表
  learning/        标准库 8 特征岭回归候选排序器
  models/          带 schema 校验的排序模型权重
  evaluation/      指标汇总、V4/V9.1 归一化评分、小规模精确 Oracle、独立验解
  io/              场景序列化、SHA256 校验、原子写入、MovingAI 地图导入
  experiments/     Legacy / V4 / V9.1 / BCRD 批量基准入口
  api.py / cli.py / web/  应用服务层、命令行与本地 Web 可视化回放
tests/             单元与 CLI/HTTP 集成测试（运行 make check / make coverage 核验）
scripts/           基准审计、敏感性实验、图表与 PDF 生成及契约检查脚本
docs/              系统架构、用法说明、各阶段设计与评审文档
research/          WEPA 推荐交付包（recommended-20261024）与已归档 DQN 实验包（dqn-experiment-v2）
results/           现行三套敏感性实验报告、总结 PDF 与历史结果索引（见 results/README.md）
runs/              本机临时运行输出目录（已 gitignore）
```

## 7. 开发与核验

```bash
make check        # ruff lint + 格式检查 + 全部单元与集成测试
make coverage     # 覆盖率门槛 80%
uv run python scripts/verify_sensitivity_evidence.py verify results/wepa-dev-sensitivity-20261120
uv run python research/recommended-20261024/verification/verify.py
```

更多测试、前端契约检查与实验复现命令见 [docs/usage.md](docs/usage.md)。

## 8. 数据与许可

MovingAI 公开地图（[ODC-By v1.0](https://opendatacommons.org/licenses/by/1-0/)，见 [data/NOTICE.md](data/NOTICE.md)）；SLAPStack/WEPAStacks 真实订单流（见 [research/recommended-20261024/data/README.md](research/recommended-20261024/data/README.md)）。工程参考与许可边界见 [NOTICE.md](NOTICE.md)。
