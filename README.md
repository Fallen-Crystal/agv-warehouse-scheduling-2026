# 仓库穿梭无人车（AGV）智能调度系统

本项目面向多取货任务并发的自动化立体仓库场景，构建了一套完整的 **AGV 调度算法、离散时空无碰撞仿真、独立物理验解与本地 Web 可视化平台**。通用引擎和 Web 回放使用 Python 3.10+ 标准库。课程报告主方案单独使用 OR-Tools CP-SAT。

---

## 1. 最终采用版本与代码对应关系

本项目沿“自研通用调度仿真平台”与“真实工业订单流算法优化”两条主线迭代演进，**最终定型采用的版本及对应源码如下**：

| 应用场景 | 最终采用版本与算法 | 核心机制 | 对应代码目录与启动入口 |
|---|---|---|---|
| **课程报告主方案** | **货位—车辆联合优化与截单后反事实推演** | CP-SAT 联合选择车辆、订单组与合法货位，整批 SIPP 试排，截单后比较剩余轨迹并保留更优参考 | [课程方案与运行入口](research/course-report/README.md) · [正式实验数据](results/course-report/README.md) |
| **2026-10 WEPA 推荐版** | `gate` | 事件门控滚动派单 + 软分区 GA + 预约表 SIPP；轻量对照为 `gate_preview3` | [原运行入口](research/recommended-20261024/current/run.py) |
| **通用多工况调度与可视化平台（工程主包）** | **`src/agv/` v0.6.0（V9.1 + SIPP/BCRD 引擎）** | V4 分层动态推荐 `bcrd_budget`；Legacy 静态推荐 `sipp_batch`；V9.1 静态推荐 `sipp_stream_bcrd`（`max_batches=2`）；内置本地交互回放界面 | 源码：`src/agv/`<br>入口：`agv`（等价于 `python -m agv`）及 `agv serve` |

---

## 2. 环境配置与手动复现指南

### 2.1 环境要求

- **Python 3.10 及以上**（推荐 Python 3.12，macOS / Linux / Windows 均可直接运行）
- 通用引擎和 2026-10 的 `gate` 使用标准库。课程报告主方案用 `requirements.txt` 中指定的 OR-Tools 版本。

### 2.2 安装与启动环境（任选一种方式）

**方式 A：标准 Python 虚拟环境（通用推荐，无需额外工具）**

```bash
git clone https://github.com/Fallen-Crystal/agv-warehouse-scheduling-2026.git
cd agv-warehouse-scheduling-2026

python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell 请执行: .venv\Scripts\Activate.ps1
pip install -e .                 # 若需运行代码规范与覆盖率检查，改为: pip install -e ".[dev]"
```

**方式 B：使用 `uv` 一键同步**

```bash
uv sync --extra dev
```

> 提示：下文命令默认已激活虚拟环境（使用 `uv` 时在命令前加 `uv run` 即可）。所有输出命令默认拒绝覆盖已有文件，如需重复写入同一路径请加上 `--overwrite`。

### 2.3 一键复现最终采用版本（建议按以下 4 步验证）

**步骤 1：运行课程报告最终方案**

```bash
python -m pip install -r research/course-report/requirements.txt
python research/course-report/run.py --case day19 --seed 0 --output runs/course-day19.json
```

默认运行货位—车辆联合优化与截单后推演，输出验解结果。固定货位和仅联合优化的对照分别使用 `--mode fixed` 和 `--mode joint`。

**2026-10 WEPA `gate` 复现命令**

```bash
python research/recommended-20261024/current/run.py \
  --case wepa-day45-bin4335 \
  --seed 0 \
  --output runs/wepa-gate-demo.json
```

预期结果：脚本完成 900 秒窗口仿真与独立物理验解，终端输出 JSON 摘要（`"profile": "gate"`、`"valid": true`、`"tasks": 40`、`"F": 0.64338`），完整轨迹保存至 `runs/wepa-gate-demo.json`。

**步骤 2：运行自研通用引擎最终版（主线 A · `src/agv/` V4 / V9.1 调度）**

```bash
# V4 分层货架动态场景（推荐 bcrd_budget）
agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 \
  --algorithm bcrd_budget --output runs/v4-bcrd-demo.json

# V9.1 混合背靠背货架静态场景（推荐 sipp_stream_bcrd）
agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 \
  --algorithm sipp_stream_bcrd --output runs/v91-bcrd-demo.json
```

预期结果：终端分别输出 JSON 摘要（V4 示例：`"feasible": true, "completed": 18, "makespan": 151`；V9.1 示例：`"feasible": true, "completed": 12, "makespan": 249`）。

**步骤 3：启动本地 Web 可视化仿真回放界面**

```bash
agv serve                      # 自动分配 127.0.0.1 空闲端口并打开浏览器；也可加 --port 8000 或 --no-browser
```

预期结果：终端打印本地访问地址 `http://127.0.0.1:<端口>/` 并自动打开浏览器。在页面中可直接切换 Legacy / V4 / V9 / V9.1 仓库布局与全部内置调度算法，动态观察 AGV 取货、避碰等待与回库全过程。

**步骤 4：运行全量自动化测试与冻结证据校验**

```bash
python -m unittest discover -s tests -t .
python research/course-report/verify_results.py
python research/recommended-20261024/verification/verify.py
python scripts/verify_sensitivity_evidence.py verify results/wepa-dev-sensitivity-20261120
```

更多命令行参数、批量基准脚本与敏感性实验复现命令见 [docs/usage.md](docs/usage.md)。

---

## 3. 实验思路与演进脉络

仓库围绕“**多任务并发下的无碰撞时空路径规划 + 多车任务指派**”问题，分两条互补主线逐步迭代：

### 3.1 两条研究主线与评价指标

| 主线 | 仿真场景 | 对应代码 | 目标函数（越低越好） |
|---|---|---|---|
| **主线 A：自研通用调度引擎** | Legacy 规则栅格、V4 分层单面货架、V9/V9.1 混合背靠背货架 | `src/agv/` | V4 / V9.1 采用同场景 `baseline` 归一化评分： $`F = 0.5\frac{T}{T_{\mathrm{ref}}} + 0.3\frac{R}{R_{\mathrm{ref}}} + 0.2\frac{D}{D_{\mathrm{ref}}}`$ ；Legacy 场景直接比较平均流程时间 `R`、完工时间 `T` 与总步数 `D` |
| **主线 B：WEPA 真实订单流** | 62×47 大型地图、6 辆 AGV、5 层货架；课程报告用 30/60 分钟窗口与同步合成批次，`gate` 用 900 秒窗口 | [课程方案](research/course-report/) · [2026-10 WEPA](research/recommended-20261024/) | 固定尺度线性评分： $`F = 0.5\frac{T}{900} + 0.3\frac{R}{900} + 0.2\frac{D}{5400}`$ |

- **指标统一定义**：**T** 为最后一单完成时刻（主线 B 不含最终返库阶段），**R** 为订单从发布到完成的平均耗时，**D** 为全部车辆总移动步数/里程（含最终返库）。
- **改善率约定**：全仓库报告中的改善率均定义为 `100% × (1 − 候选指标 / 基线指标)`，**正数表示指标降低（方案更优）**。两条主线采用各自独立的场景和归一化尺度，分别在各自协议内做横向对比。

### 3.2 算法演进路径与方案速查

| 方案名称 | 所属主线 | 核心做法 | 演进定位 |
|---|---|---|---|
| `baseline` | A | 距离贪心派单 + 时空 A* 路径规划 | 初始基线 |
| `joint_only` / `joint_batch` | A | LNS 拥堵车队联合重排 / 静态首轮批次滚动 | 解决局部碰撞与初始分配 |
| `sipp_budget` | A | SIPP 安全区间压缩 + 拥堵关联修复（限制候选预算） | 提升规划效率 |
| `sipp_batch` | A | 静态场景下对首轮多车分配做有序批次滚动优化 | Legacy 静态优选 |
| `bcrd_budget` | A | 高积压工况下在独立影子环境中试派候选批次序列 | V4 分层动态优选 |
| `sipp_stream_bcrd` | A | V9.1 混合货架流式关闭规则 + BCRD 有序批次试派 | V9.1 静态优选 |
| `fcfs` / `eta` | B | 先到先服务 / 最早到达优先 | 规则基线 |
| `hungarian` | B | 基于当前局部代价矩阵的匈牙利指派 | 局部一次性匹配对照 |
| `simple` → `wide` | B | 联合遗传算法（GA）派单；`wide` 扩大种群与代数预算 | GA 演进过程 |
| `gate` | B | `wide` + 事件门控（低负载免触发 GA）+ SIPP 物理预演 | 2026-10 WEPA 协议推荐 |
| `joint` | B | CP-SAT 联合选择车辆、订单和货位，整批 SIPP 试排 | 课程报告货位消融方案 |
| **`counterfactual`** | B | 流式阶段联合优化，截单后推演并保留更优参考轨迹 | **课程报告默认方案** |
| `hga` | B | 以匈牙利解替换部分随机初始个体的遗传算法 | 初始化消融对照 |
| `gate_preview3` / `gate_gen8` / `gate_gen24` | B | 预演次数降为 3 / 代数降为 8 / 代数扩大至 24 | 计算预算敏感性对照 |
| `wide_adaptXY` | B | `X`=变异率自适应开关、`Y`=交叉率自适应开关 | 自适应算子对照 |
| `dqn-experiment-v2` | B | Double DQN 在局部匹配与自适应 GA 间动态切换 | 历史探索归档（相对纯自适应 GA −0.37%，未选用） |

---

## 4. 核心实验结果汇总

### 课程报告正式实验（294 次）

| 数据组 | 案例数 | 正式运行 | 联合优化相对自适应 GA 的 F 改善 | 完整方案相对自适应 GA 的 F 改善 | 推演相对仅联合优化的 F 改善 |
|---|---:|---:|---:|---:|---:|
| 主要真实窗口 | 5 | 105 | 20.82% | 20.84% | 0.0332% |
| 补充真实窗口 | 3 | 63 | 5.00% | 5.00% | 0.00% |
| 同步合成批次 | 6 | 126 | 41.32% | 43.23% | 3.53% |

改善率按同案例、同种子配对后取均值。正式实验的七方案汇总、逐次结果和推演计数可核对，报告的 360 次灵敏度实验另列来源及可核验范围。[课程报告实验索引](results/course-report/README.md)

以下是既有三套对照实验，共 561 次运行，全部通过对应的独立验解。

### 主线 B（WEPA 真实订单流：200 次开发窗 + 156 次既有验证窗复评）

1. **GA 方案全面优于规则基线**：在 4 个既有验证窗口（`day40/61/83/87`）上，`gate` 相对 `fcfs` 改善 **+5.45%**、相对 `eta` 改善 **+2.43%**、相对 `hungarian` 改善 **+3.87%**，4 个日期全部获得正改善（4/0/0）。
2. **该阶段推荐 `gate`**：`gate` 与 `wide` 的综合评分极为接近（验证窗 −0.10%，0/2/2；开发窗 +0.11%，1/3/0），而 `gate` 通过事件门控将开发窗的 GA 触发次数减少 **63%**（205 次 vs 560 次），计算触发更克制，且延续 2026-10 推荐主线口径（10 月单 seed 0 均值 0.896406，本轮 seed 0–2 均值 0.899159）。
3. **跨窗口泛化检验**：开发窗表现最好的 `hga`（相对 `gate` +0.95%）与仅开交叉自适应 `wide_adapt01`（相对 `wide_adapt00` +0.94%）在 4 个既有验证窗口上均出现回退（`hga` −1.12%，0/0/4；`wide_adapt01` −0.54%，1/0/3），因此该协议继续推荐 `gate`。
4. **预算与算力权衡**：将代数扩大至 24 代（`gate_gen24`）反而使验证窗表现下降 −1.41%（0/0/4），说明默认 16 代预算充足；将完整预演降至 3 次（`gate_preview3`）可减少约 **44%** CPU 耗时（21.66s → 12.09s），F 仅变化 −0.33%，适合算力受限环境。

### 主线 A（自研通用引擎：205 次 5-seed 演进与超参扫描）

1. **V4 分层动态场景**：`bcrd_budget` 相对 `baseline` 将综合目标 F 改善 **+3.01%**（0.9699 ± 0.0191，4 胜 1 平 0 负），平均单次耗时仅 0.17 秒，是该场景推荐方案。
2. **Legacy 静态场景**：`sipp_batch` 相对 `baseline` 将平均流程时间 R 改善 **+2.62%**（5/0/0），总行驶步数减少 4.24%，且运行快于同质量的 `joint_batch`（10.27s vs 14.15s）。
3. **V9.1 静态与超参数扫描**：静态并发场景下 `sipp_stream_bcrd` 与 `sipp_stream_matching` 均使 F 改善约 **+1.53%**，`max_batches` 从 1 增至 2 即可获得完整收益（2/4/6 结果一致，取 2 即可）；Legacy 动态下 `trial_budget` 在 2–10 范围内波动极小，算力敏感时可取较小的 `2` 或默认 `6`。V9.1 动态低负载场景下队列未触及 BCRD 触发阈值，各流式方案与基线持平。

### 实验报告与历史演进文档索引

| 实验 ID | 主线 | 内容概览 | 有效运行 | 报告入口 |
|---|---|---|---:|---|
| `wepa-dev-sensitivity-20261120` | B | WEPA 4 开发窗：7 方案演进 + 预算 2×2 + 自适应 2×2 | 200 | [REPORT.md](results/wepa-dev-sensitivity-20261120/REPORT.md) |
| `wepa-val-sensitivity-20261121` | B | WEPA 4 既有验证窗复评 + 扩大预算与组合对照 | 156 | [REPORT.md](results/wepa-val-sensitivity-20261121/REPORT.md) |
| `core-sensitivity-20261121` | A | 自研引擎 Legacy / V4 / V9.1 演进与超参扫描（5 seeds） | 205 | [REPORT.md](results/core-sensitivity-20261121/REPORT.md) |

全部现行与历史阶段结果索引见 [results/README.md](results/README.md)；各阶段演进与优化说明集中在 `docs/`（涵盖 [v1](docs/history/v1-report.md) → [v2 SIPP](docs/v2-results.md) → [v4](docs/v4-review.md) → [BCRD](docs/bcrd-results.md) → [v9](docs/v9-review.md) → [v9.1](docs/v91-optimization.md)）。

---

## 5. 仓库目录结构

```text
agv-warehouse-scheduling-2026/
├── src/agv/                        # 主线 A：自研通用调度引擎（v0.6.0，Python 标准库零依赖）
│   ├── domain.py                   #   任务与场景数据模型、合法性校验与示例生成
│   ├── warehouse/                  #   V4 / V9 / V9.1 分层与混合背靠背货架几何及层序约束
│   ├── simulation.py               #   唯一真实执行状态机、时空预约更新与重规划审计
│   ├── planning/                   #   时空 A*、SIPP 安全区间规划、增量预约索引、LNS 联合修复
│   ├── dispatch/                   #   贪心、匹配、流式派单、BCRD 影子试派、静态批滚动与算法注册表
│   ├── evaluation/                 #   指标统计、归一化评分、小规模精确 Oracle 与独立物理验解
│   ├── io/ & experiments/          #   场景序列化、MovingAI 地图导入与批量基准入口
│   └── api.py / cli.py / web/      #   统一应用接口、agv 命令行入口与本地 Web 可视化前端
├── research/
│   ├── course-report/             # 课程报告主方案、运行方式与输入来源
│   ├── recommended-20261024/       # 2026-10 WEPA gate 源码、数据与演进报告
│   └── dqn-experiment-v2/          # 历史探索归档：自适应 GA + Double DQN 源码、权重与评估结果
├── docs/                           # 系统架构、命令手册、历次版本演进与算法调研文档
├── results/                        # 现行三套敏感性实验数据/图表及历史阶段结果（见 results/README.md）
├── examples/ & data/               # 静态/动态标准算例与 MovingAI 公开地图数据
├── scripts/                        # 基准实验、敏感性分析、图表绘制与证据校验脚本
├── tests/                          # 单元测试与 CLI / Web 集成测试
└── runs/                           # 本地复现临时输出目录（已配置 .gitignore）
```

---

## 6. 数据来源与许可说明

- **MovingAI 公开仓库地图**：遵循 [ODC-By v1.0](https://opendatacommons.org/licenses/by/1-0/) 许可，归属信息见 [data/NOTICE.md](data/NOTICE.md)。
- **SLAPStack / WEPAStacks 真实订单流**：原始数据说明与许可见 [research/recommended-20261024/data/README.md](research/recommended-20261024/data/README.md)。
- **项目来源与学术借鉴说明**：见 [NOTICE.md](NOTICE.md) 与 [docs/research/engineering-and-sipp.md](docs/research/engineering-and-sipp.md)。
