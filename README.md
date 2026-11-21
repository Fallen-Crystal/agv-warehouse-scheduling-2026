# Warehouse AGV Scheduling（仓库穿梭无人车智能调度）

面向多取货任务并发场景的仓库穿梭无人车（AGV）智能调度、离散时空仿真与独立验解平台。核心运行零第三方依赖（Python 3.10+ 标准库），支持 CLI、本地 Web 交互回放以及可复现的多 Seed / 超参数对照实验。

---

## 1. 整体研究脉络：两条演进主线

仓库从最初的离散栅格基线出发，沿两条互补主线持续迭代，并在本轮完成了代码去重、热点加速与全链路多 Seed 超参数验证：

```text
主线 A：自研通用调度引擎 (src/agv/) —— 合成/分层/混合货架多工况
  baseline (距离贪心)
    ├──► joint_only / joint_batch (A* + LNS联合重规划 / 静态首轮批次滚动)
    ├──► sipp_joint ─► sipp_conflict ─► sipp_budget / sipp_batch (SIPP + 拥堵关联修复 + 预算)
    │                                         └──► sipp_learned (8特征线性候选排序)
    └──► 业务规则演进：v4 (2L分层货架) ─► bcrd_budget (影子试派)
                         └─► v9 (混合背靠背货架+待命) ─► v9.1 (流式关闭+选点定位+BCRD尾保护)

主线 B：WEPAStacks 真实订单流研究 (research/) —— 62×47大型地图 / 6车 / 5层 / 900s窗口
  fcfs ─► eta ─► simple (早期GA) ─► wide (扩预算GA) ─► gate (推荐默认：门控+联合GA+SIPP)
    ├──► hungarian (纯局部代理匹配) ─► hga (匈牙利初始化GA)
    └──► dqn-experiment-v2 (双概率自适应GA算子 + Double DQN双动作选择)
```

- **关于目标函数口径**：
  - **主线 A（V4/V9/V9.1 合成规则）**：采用同场景固定基线归一化综合目标 $F = 0.5\frac{T}{T_{\text{ref}}} + 0.3\frac{R}{R_{\text{ref}}} + 0.2\frac{D}{D_{\text{ref}}}$（越低越好）。
  - **主线 B（WEPA 真实订单流）**：采用独立固定尺度线性目标 $F = 0.5\frac{T}{900} + 0.3\frac{R}{900} + 0.2\frac{D}{5400}$（$T$ 不含最终返库，$D$ 含最终返库；越低越好）。不同协议与窗口长度的绝对 $F$ 不直接跨口径混排。

---

## 2. 多 Seed 稳定性与超参数敏感性实验汇总

为在固定参数主实验之外系统评估**跨版本演进效果、随机种子波动与超参数敏感性**，仓库内已完成三套相互补充、全部经过独立物理验解的实验（合计 **561 次**有效运行）：

| 实验集 | 覆盖对象 | 有效次数 | 核心发现 | 报告与图表 |
|---|---|---:|---|---|
| **WEPA 开发集矩阵**<br>(`wepa-multiseed-sensitivity-20261120-v2`) | `fcfs`/`eta`/`hungarian`/`simple`/`wide`/`gate`/`hga` + 预算 `2×2` + 自适应 `2×2`（4 开发窗） | **200 / 200** | 开发集上 `hga` 最低（F=0.9101, SD=0.00355）；`preview=3` 省 45.28% CPU；只开交叉自适应（`wide_adapt01`）优于双开（变异率 86%+ 饱和触顶） | [中文报告](results/sensitivity-20261120-v2/report/中文实验报告.md) · [9页PDF](output/pdf/AGV多seed稳定性与参数敏感性研究.pdf) |
| **WEPA 未见验证集补充**<br>(`wepa-validation-sensitivity-20261121`) | 4 个未见验证窗（`day40/61/83/87`），含上界 `gate_gen24` 与组合 `hga_adapt01` | **156 / 156** | **关键泛化结论**：`wide`(0.8983) / `gate`(0.8992) 在未见窗稳健最优；`hga`(-1.12%) 与 `gate_gen24`(-1.41%) 在验证窗过拟合回退；`hga_adapt01` 显著拉回 `hga`(+0.79%) 并获最低 seed SD(0.00521)；`gate_preview3` 稳健降耗 44.2% CPU | [验证集报告](results/sensitivity-20261121-validation/REPORT.md) · [演化图](results/sensitivity-20261121-validation/figures/validation_evolution.svg) · [参数对比图](results/sensitivity-20261121-validation/figures/validation_budget_and_adaptive.svg) |
| **主引擎演进与参数扫描**<br>(`core-sensitivity-20261121`) | `src/agv/` Legacy(静/动) + V4 + V9.1，5 seeds，`trial_budget`/`interval`/`max_batches` | **205 / 205** | Legacy 静态 `sipp_batch` 降低 Flow 2.62% 且总步数少 4.24%；V4 `bcrd_budget` 降 F 3.01%；V9.1 高负载下 `max_batches>=2` 解锁 -1.5% F，`trial_budget=6` 与 `max_batches=2~4` 性价比最佳 | [核心引擎报告](results/core-sensitivity-20261121/REPORT.md) · [静态图](results/core-sensitivity-20261121/figures/legacy_static_flow.svg) · [动态超参图](results/core-sensitivity-20261121/figures/legacy_hyperparam_sensitivity.svg) · [V9.1图](results/core-sensitivity-20261121/figures/v91_evolution_and_bcrd_batches.svg) |

> **实证结论**：当前仍保留 **`gate`** 作为 WEPA 推荐默认方案（未见窗稳健且显著优于 `fcfs` +5.45% / `eta` +2.43% / `hungarian` +3.87%）；若预算受限，推荐 **`gate_preview3`**（CPU 减半、质量接近）。在自研主引擎侧，`sipp_budget`（动态）、`sipp_batch`（静态）与 `bcrd_budget`/`sipp_stream_bcrd`（高负载分层仓库）构成了清晰的性能阶梯。

---

## 3. 快速开始与常用命令

### 3.1 安装环境（推荐 `uv` 或 `venv`）

```bash
uv sync --extra dev          # 或 python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

### 3.2 启动本地可视化交互界面

```bash
.venv/bin/agv serve          # 仅绑定 127.0.0.1，浏览器内可切换 Legacy/V4/V9/V9.1 及全部内置调度算法
```

### 3.3 运行主线 A（自研通用引擎 CLI）

`python -m agv` 等价于 `agv`，默认拒绝覆盖已有输出文件（如需覆盖请显式加 `--overwrite`）：

```bash
# 1. Legacy 场景（SIPP + 拥堵关联修复 + 6 候选预算）
agv run --input examples/scenarios/dynamic_medium_burst.json --algorithm sipp_budget --output runs/demo.json

# 2. 静态首轮批次滚动优化（static only）
agv run --profile legacy --mode static --tasks 12 --vehicles 4 --algorithm sipp_batch --output runs/static-batch.json

# 3. V4 分层货架 + BCRD 有序批次派单
agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 --algorithm bcrd_budget --output runs/v4-bcrd.json

# 4. V9.1 流式订单 + 批次间安全待命 / BCRD 尾部保护
agv run --profile v9.1 --mode dynamic --tasks 12 --vehicles 4 --algorithm sipp_stream_dispatch --output runs/v91-stream.json
agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 --algorithm sipp_stream_bcrd_tail --output runs/v91-bcrd.json
```

### 3.4 运行主线 B（WEPA 真实订单推荐方案）

```bash
python research/recommended-20261024/current/run.py --case wepa-day45-bin4335 --seed 0 --output runs/wepa-demo.json
```

详细数学模型、规则边界、对照与参考文献见 [推荐方案材料](research/recommended-20261024/README.md)。

### 3.5 开发检查、对比实验复现与证据核验

```bash
make check                                                              # ruff lint + 格式检查 + 279 项 unittest/集成测试
make coverage                                                           # 覆盖率检查（当前 86%，门槛 80%）
node --check src/agv/web/static/app.js && node scripts/check_viewer_contracts.mjs
python research/recommended-20261024/verification/verify.py             # 校验 WEPA 材料包 114 个指纹与 ZIP CRC
python scripts/verify_sensitivity_evidence.py verify results/sensitivity-20261120-v2

# 复现本轮补充的多 Seed 与超参数敏感性实验：
.venv/bin/python scripts/run_core_sensitivity.py --output runs/core-sensitivity-check --workers 6
.venv/bin/python scripts/run_wepa_validation_sensitivity.py --output runs/wepa-val-check --workers 6
```

---

## 4. 项目结构

```text
src/agv/
  domain.py             Task / Scenario 数据模型、坐标校验、结构深拷贝与生成示例
  warehouse/            V4/V9 分层货架、通道、设施几何与同面先后层序约束
  simulation.py         唯一真实执行状态机、预约更新与重规划全未来审计
  planning/             时空 A* 参照、SIPP 安全区间规划、增量预约索引、几何缓存、LNS 联合修复
  dispatch/             贪心/批量匹配/定位/流式派单/BCRD 影子滚动/静态首轮批次规划/统一注册表
  learning/             标准库 8 特征岭回归候选排序器与训练流程
  models/               带 schema 校验的候选排序模型权重
  evaluation/           指标汇总、V4/V9.1 归一化评分、小规模精确 Oracle、独立验解与失败诊断
  io/                   场景序列化与 SHA256 校验、原子写入、MovingAI 公开地图导入
  experiments/          Legacy / V4 / V9.1 / BCRD 批量基准入口
  api.py                应用服务层（选项校验、场景构建、单次/批量执行）
  web/                  本地 HTTP 服务与前端 HTML/JS/CSS
  cli.py                统一命令行入口

tests/                  单元测试与 CLI/HTTP 集成测试（279 tests，覆盖率 86%）
scripts/                基准审计、敏感性实验、报告/图表/PDF 生成与契约检查脚本
examples/               可复用静态/动态场景与冻结实验协议
data/                   归属公开 MovingAI 仓库地图及独立声明
docs/                   系统架构、V4/V9/V9.1/BCRD 设计与评审报告、敏感性研究文档
research/
  recommended-20261024/ WEPA 推荐 GA-SIPP 完整交付包（含原始数据与历史归档校验）
  dqn-experiment-v2/    去重整理后的自适应 GA + 匈牙利 + DQN 研究源码、文档与最佳权重
results/
  summary_tables/       UTF-8 编码的 22 份全量正式/历史实验汇总 CSV
  sensitivity-20261120-v2/         WEPA 开发集 200 次多 Seed 与超参数敏感性冻结证据
  sensitivity-20261121-validation/ WEPA 未见验证集 156 次补充对照与组合实验
  core-sensitivity-20261121/       主引擎 205 次跨版本演进与超参数敏感性实验
  v1/ v2/ v4/ v9/ v91/ bcrd/ ...   各阶段独立验解留出证据与代表轨迹
output/pdf/             可交付的多 Seed 敏感性研究 9 页 PDF 报告
runs/                   本机生成的临时运行目录（已 gitignore）
```

---

## 5. 核心算法、数据声明与边界说明

1. **核心算法机制**：
   - **SIPP 安全区间压缩**：将 `(位置, 时刻)` 状态空间压缩为 `(位置, 最大安全时间区间)`，显式校验逆向边交换冲突与连续服务时长；`VertexReservations` 增量维护最大时域与有序时间线。
   - **拥堵关联 LNS 修复**：优先重排存在空间重叠与延迟的车辆对，保留全车队兜底候选；采用不可变地图缓存与轻量审计状态克隆（`apply_replan` 全未来验证）。
   - **BCRD 影子试派与静态首轮滚动**：高积压工况下在独立可见影子环境中对候选批次序列做保底滚动；静态全可见场景可通过 `joint_batch` / `sipp_batch` 筛选更优初始分配。
   - **小规模精确参照 Oracle**：`agv.evaluation.oracle.exact_static` 在无刻意空等假设下枚举小实例（`<=5` 任务 / `<=2` 车）全分配与全排列，用于评估启发式最优性差距。
2. **公开数据与参考边界**：
   - 包含 MovingAI 公开地图（[ODC-By v1.0](https://opendatacommons.org/licenses/by/1-0/)，见 [data/NOTICE.md](data/NOTICE.md)）与 SLAPStack/WEPAStacks 真实订单流（见 [research/recommended-20261024/data/README.md](research/recommended-20261024/data/README.md)）。
   - 货位映射、层数与单元运动速率均为课程仿真假设，不宣称未覆盖场景的全局最优或真实工厂物理复现。工程参考与许可边界见 [NOTICE](NOTICE.md)、[架构文档](docs/architecture.md) 与 [研究记录](docs/research/engineering-and-sipp.md)。
