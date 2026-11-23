# 工程结构参考与安全区间路径规划（SIPP）原理分析

调研日期：2026-10-15

本文整理了重构 v2 架构与实现安全区间路径规划（SIPP）期间调研的开源工程参考、SIPP 离散正确性推导以及 MovingAI 公开地图的转换规范。所有开源仓库链接均固定到实际查阅的 Git 提交，确保出处可追溯；所有性能与调度效果均以本项目同场景实测为准。

## 1. 开源工程参考与架构借鉴

| 参考项目与固定提交 | 重点查阅文件 | 对本项目的架构启发 |
|---|---|---|
| [w9-pathfinding (`8ff393ba`)](https://github.com/andreyd41/w9-pathfinding/tree/8ff393ba23012e6f4877df0b56d34c6599bd5786) | `pyproject.toml`、`test_space_time_a_star.py`、`test_reservation_table.py`、官方文档 | 按领域分包、独立测试预约表（含永久占位与副本隔离）；保持纯 Python 轻量化实现 |
| [MAPF-LNS (`95785de6`)](https://github.com/Jiaoyang-Li/MAPF-LNS/tree/95785de66f8fbdb91fed871e1a56c8c563f39b1f) | `CMakeLists.txt`、`driver.cpp`、`LNS.cpp`、`SIPP.cpp`、CI 工作流 | 统一入口、显式参数记录、求解后自动 `validateSolution()`、迭代统计与固定示例 smoke test |
| [RHCR (`d009a3bd`)](https://github.com/Jiaoyang-Li/RHCR/tree/d009a3bd716419b0d6c04aead9dbca1720c012da) | `README.md`、`driver.cpp`、`BasicSystem.cpp`、`SIPP.h`、macOS CI | 上层仿真与低层求解器（A*/SIPP）可插拔替换，完整持久化种子、窗口配置与轨迹 |
| [libMultiRobotPlanning (`4c75fa20`)](https://github.com/whoenig/libMultiRobotPlanning/tree/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0) | `sipp.hpp`、`mapf_prioritized_sipp.cpp`、`test_sipp.py`、`test_mapf_prioritized_sipp.py`、CI | 算法与环境接口解耦、可执行样例与测试夹具分离，覆盖交换位置与起点即终点等边界测试 |

具体参考代码链接：
- w9-pathfinding：[预约表测试](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/tests/mapf/test_reservation_table.py)、[时空搜索测试](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/tests/mapf/test_space_time_a_star.py)、[构建配置](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/pyproject.toml)。
- MAPF-LNS：[入口](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/driver.cpp)、[验解与统计](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/LNS.cpp)、[Ubuntu CI](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/.github/workflows/test_ubuntu.yml)。
- RHCR：[入口参数](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/src/driver.cpp)、[配置与轨迹输出](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/src/BasicSystem.cpp)、[macOS CI](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/.github/workflows/test_macos.yml)。
- libMultiRobotPlanning：[构建 CI](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/.github/workflows/build.yml)、[SIPP 测试](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/test/test_sipp.py)、[多车 SIPP 测试](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/test/test_mapf_prioritized_sipp.py)。

## 2. 本项目的模块化分层设计

结合课程项目的纯 Python 定位与可复现需求，采用以下单一职责分层（核心运行零第三方依赖，绘图与检查工具作为可选依赖）：

| 模块路径 | 核心职责 | 边界约束 |
|---|---|---|
| `src/agv/domain.py` | 场景、订单、地图合法性与任务生成 | 独立于 Web 与实验脚本 |
| `src/agv/simulation.py` | 唯一真实时钟、车辆状态、任务归属、轨迹与原子提交 | 严格隔离未来订单与展示层 |
| `src/agv/planning/` | A*、SIPP、取送路线与联合后缀修复 | 共用统一单段契约，保留 A* 作参照 |
| `src/agv/dispatch/` | 贪心、可见订单匹配与调度主循环 | 仅通过 `observe()` 与环境公开接口交互 |
| `src/agv/evaluation/` | 指标计算、独立轨迹验解与失败诊断 | 基于实际轨迹与事件独立核验 |
| `src/agv/experiments/` | 场景矩阵、固定种子、配对运行与汇总 | 完整保留参数与失败记录 |
| `src/agv/io/` | 场景与结果文件的校验读写 | 原子写入，格式清晰 |
| `src/agv/web/` | 交互展示与轨迹回放 | 复用统一注册表与仿真引擎 |
| `tests/unit/`、`tests/integration/` | 局部契约与跨模块流程回归 | 支持安装后包外运行 |
| `docs/`、`examples/`、`results/` | 文档、复现输入与实测数据 | 历史版本独立归档 |

## 3. SIPP 原论文与本项目离散适配

SIPP 源自 Mike Phillips 与 Maxim Likhachev 的 *SIPP: Safe Interval Path Planning for Dynamic Environments*（ICRA 2011, pp. 5628–5635；见 [作者原文](https://www.cs.cmu.edu/~maxim/files/sipp_icra11.pdf)、[CMU RI 记录](https://publications.ri.cmu.edu/sipp-safe-interval-path-planning-for-dynamic-environments)、[SBPL 出版页](https://sbpl.github.io/publications/sipp-icra11/)）。其核心思想是以 `(位置, 安全时间区间)` 替代 `(位置, t)`，把到达时刻记为区间状态标签，从而大幅压缩连续等待带来的状态爆炸。

本项目将其适配至单位步长、四邻接移动/等待、离散时间步的仓库模型中，完整支持**连续装卸服务占位、服务禁用时段、有限 horizon 与对向边交换避碰**，并保持与时空 A* 完全一致的 `leg` 接口和逐步轨迹输出。SIPP 专注优化给定静态/动态预约表下的单段最早到达搜索；上层任务分配、优先级顺序与多车协调则由调度层与重规划层承担。

## 4. 状态支配与完整约束推导

### 4.1 区间合并与支配条件

对网格 `p`，将 `[now, horizon]` 内未被顶点预约占用的时刻划分为极大连续闭区间 `[lo, hi]`。搜索状态键为 `(p, interval_id)`，标签为已知最早到达时刻 `arrival`。若同一安全区间内存在两次到达 `a <= b`，由于 `[a, b]` 全程安全且允许单位耗时原地等待，先到达者可原地等到 `b` 再沿用后到达者的所有后续路径，因此在最小化完成时间目标下，`a` 严格支配 `b`。

该支配关系成立的前提是：
1. 原地等待合法且代价等于经过的时间步；
2. 单段状态中不含尚未编码的速度、朝向、载荷阶段或电量等附加维度；
3. 被支配的两次到达处于同一连续安全区间内；
4. 预约表在单次搜索期间固定，逆向边冲突在离开时刻单独校验。

（若未来扩展为单次搜索联合求解取货与送货，需在状态键中显式增加阶段标识，将“已取货”与“未取货”区分为不同状态。）

### 4.2 区间转移与逆向边避碰

设车辆在源格 `p` 的安全区间（上限 `upper`）于 `arrival` 到达，拟转移至相邻格 `q` 的安全区间 `[lower, end]`。合法到达时刻 `enter` 须同时满足：

```text
enter >= max(arrival + 1, lower)
enter <= end
enter - 1 <= upper
(enter - 1, q, p) not in existing_edges
```

其中第三条允许车辆在源格安全的最后一拍 `upper` 出发并于 `upper + 1` 进入 `q`；第四条显式检查他车 `q -> p` 的对向交换冲突（与 [w9 ReservationTable 文档](https://w9-pathfinding.readthedocs.io/stable/mapf/ReservationTable.html)、[SpaceTimeAStar 文档](https://w9-pathfinding.readthedocs.io/stable/mapf/SpaceTimeAStar.html) 将顶点与边预约分离的做法一致；而 [libMultiRobotPlanning 的优先级示例](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/example/mapf_prioritized_sipp.cpp) 未在回调中内置逆向边检查，因此本项目单独实现了完整的边预约扫描）。搜索从最早合法 `enter` 开始，跳过被逆向边阻塞的出发时刻，并采用忽略动态预约的静态最短路作为一致启发函数。

### 4.3 连续装卸服务约束与路径展开

对于持续 `d` 步的服务，若从时刻 `begin` 启动，则车辆在闭区间 `[begin, begin + d]` 均停留在目标格，服务动作占用半开区间 `[begin, begin + d)`，须满足：

```text
begin >= arrival
begin + d <= safe_interval.end
all(t not in service_blocked for t in range(begin, begin + d))
```

若到达时服务资源暂不可用，允许在目标格安全区间内原地等待至合法 `begin`；若当前安全区间不足以容纳完整服务，车辆可先离开目标格并于后续安全区间重入。此外，`service_blocked` 仅限制服务动作，允许其他车辆正常途径该格；已开始的服务由上层冻结剩余段以保障连续性。

回溯生成路径时，需在父格补齐隐式等待步，再拼接移动与服务占位步（与 MAPF-LNS 中 [`SIPP.cpp` 的 `updatePath`](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/SIPP.cpp) 思路一致），确保下游仿真、独立验解与可视化获得完整的逐时刻轨迹。

## 5. 差分验证与验收要点

围绕 `src/agv/planning/sipp.py` 与 `astar.py`，除仓库内常驻的 `tests/unit/test_sipp.py` 外，额外运行了 **12,000 例随机小图差分测试**（2–5 列、1–4 行、随机静态障碍与断连图、0–5 步服务、随机顶点/逆向边/服务禁用与 horizon 边界，含起点即终点场景），与逐时刻时空 A* 对照可行性与最早完成步数，并逐点逐边复核冲突与服务约束：**12,000/12,000 全部精确匹配通过**。

后续演进应持续保持以下工程验收基线：
1. 独立验解器始终核验完整历史与未来候选；
2. 差分测试以独立参考逻辑验算，不复用 SIPP 内部区间函数；
3. 持续保留起点受阻、起终点重合、horizon 端点、目标等待/离开重入及逆向边让行等边界回归用例；
4. 在完整场景配对实验中综合评估运行耗时、扩展节点数与调度质量，全面衡量区间维护与搜索压缩之间的实际权衡。

## 6. MovingAI 公开地图规范与派生边界

### 6.1 地图选型与官方资源

[Moving AI Lab MAPF 基准页](https://movingai.com/benchmarks/mapf.html) 与 [地图索引](https://movingai.com/benchmarks/mapf/index.html) 提供了标准网格地图，按本项目车辆规模筛选如下：

| 官方地图 | 尺寸 / 可通行格数 | 适用建议 |
|---|---|---|
| `warehouse-10-20-10-2-1.map` | 161×63 / 5,699 | 首选仓库几何来源，适合固定区域裁剪以适配课程车队规模 |
| `warehouse-10-20-10-2-2.map` | 170×84 / 9,776 | 适合作为不同巷道宽度的跨图留出测试 |
| `warehouse-20-40-10-2-1.map` | 321×123 / 22,599 | 规模偏大，暂缓选用 |
| `warehouse-20-40-10-2-2.map` | 340×164 / 38,756 | 规模偏大，暂缓选用 |

官方下载资源：[161×63 仓库地图 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-1.map.zip)、[对应 25 组 random 场景 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-1.map-scen-random.zip)、[170×84 仓库地图 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-2.map.zip)。`empty-8-8`、`empty-16-16` 适合作为解析与搜索 smoke test，而仓库训练与评估仍应使用真实货架几何。

### 6.2 格式解析、派生规则与许可合规

根据 [官方格式说明](https://movingai.com/benchmarks/formats.html)，地图头依次为 `type octile`、`height H`、`width W`、`map`，`.`/`G` 为可通行地面，`@`/`O`/`T` 为障碍。由于原 `.scen` 文件仅描述一次性起终点对，本项目在裁剪原图后按显式派生规则补充货架标识、停车位、取送点、装卸时长与在线订单流，并完整记录原图名、SHA-256、裁剪框 `(x0, y0, width, height)`、生成种子与连通性校验，构建“基于 MovingAI 仓库几何生成的 MAPD 派生模拟数据”。

数据遵循 [Open Data Commons Attribution License (ODC-By v1.0)](https://opendatacommons.org/licenses/by/1-0/)，发布时在 `data/` 保留来源链接、许可声明与原始/派生区分，并按官方要求引用 Stern 等（2019）*Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks*。用于候选排序器训练时，预先划分互不重叠的训练/验证/测试区域并使用独立种子，在同等候选预算下于留出区域检验真实仿真指标。
