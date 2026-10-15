# 工程结构参考与安全区间路径规划

调研与本地审查日期：2026-10-15。本文引用原论文、作者仓库、项目官方文档以及实际配置和测试源码；工程取舍与正确性推导属于本项目分析。下文没有以外部论文的性能数字推定本项目加速效果，最终速度和调度质量必须由相同场景、配置、机器上的实测支持。

## 1. 实际检查了哪些工程参考

为使参考可追溯，下表使用本次读取的 Git 树版本。仓库当前分支之后可能变化，链接固定到这些版本。

| 项目与固定版本 | 本次实际读取 | 借鉴方式与边界 |
|---|---|---|
| [w9-pathfinding，`8ff393ba23012e6f4877df0b56d34c6599bd5786`](https://github.com/andreyd41/w9-pathfinding/tree/8ff393ba23012e6f4877df0b56d34c6599bd5786) | `pyproject.toml`、`tests/mapf/test_space_time_a_star.py`、`tests/mapf/test_reservation_table.py`、官方 ReservationTable/SpaceTimeAStar 文档 | 按领域分包、对预约表单独测试；保留规划器与预约接口的边界。其 C++/Cython 构建方式与本项目纯 Python 不同，不照搬依赖。 |
| [作者 MAPF-LNS，`95785de66f8fbdb91fed871e1a56c8c563f39b1f`](https://github.com/Jiaoyang-Li/MAPF-LNS/tree/95785de66f8fbdb91fed871e1a56c8c563f39b1f) | `CMakeLists.txt`、`src/driver.cpp`、`src/LNS.cpp`、`src/SIPP.cpp`、macOS/Ubuntu 工作流 | 参考统一入口、显式求解参数、独立验解、迭代统计、固定示例 smoke test。其 C++ 求解器不是本项目源码的直接依赖。 |
| [作者 RHCR，`d009a3bd716419b0d6c04aead9dbca1720c012da`](https://github.com/Jiaoyang-Li/RHCR/tree/d009a3bd716419b0d6c04aead9dbca1720c012da) | `README.md`、`src/driver.cpp`、`src/BasicSystem.cpp`、`inc/SIPP.h`、`CMakeLists.txt`、macOS 工作流 | 参考上层仿真与低层求解器可替换、保存窗口/种子配置、保存任务及轨迹。这里只借鉴结构，仍不将当前完整未来验解称为原版窗口 RHCR。 |
| [libMultiRobotPlanning，`4c75fa20c435c440d8b6bd6dc81668ddc7296ba0`](https://github.com/whoenig/libMultiRobotPlanning/tree/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0) | `include/libMultiRobotPlanning/sipp.hpp`、`example/mapf_prioritized_sipp.cpp`、`test/test_sipp.py`、`test/test_mapf_prioritized_sipp.py`、CI | 参考算法—环境接口、可运行例子与输入 fixture 分离、边界案例测试；不用模板泛型框架替代当前简单的 Router 接口。 |

w9 的旧 GitHub 地址在本次访问时重定向到 `andreyd41/w9-pathfinding`，因此表中使用实际读取的目标仓库。它的预约表测试包含永久顶点占位与副本修改不影响原表；时空搜索测试含动态障碍、等待代价、有限深度和精确长度。其 `pyproject.toml` 此版本只声明 setuptools/Cython 构建后端。见 [预约表测试](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/tests/mapf/test_reservation_table.py)、[时空搜索测试](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/tests/mapf/test_space_time_a_star.py)、[构建配置](https://github.com/andreyd41/w9-pathfinding/blob/8ff393ba23012e6f4877df0b56d34c6599bd5786/pyproject.toml)。

MAPF-LNS 的入口会在成功求解后调用 `validateSolution()`，并分别输出总体结果与逐次迭代统计。其 Ubuntu/macOS CI 真实执行编译和一个 50 车、60 秒预算的示例，属于 smoke test，不能误称全面算法正确性证明。见 [入口](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/driver.cpp)、[验解与统计实现](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/LNS.cpp)、[Ubuntu CI](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/.github/workflows/test_ubuntu.yml)。

RHCR 的 `single_agent_solver` 参数可以选择 ASTAR/SIPP；保存结果时写出种子、求解器、规划窗口、执行窗口等配置。macOS CI 分别运行 SORTING/PBS 和 KIVA/ECBS 两组配置。见 [入口参数](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/src/driver.cpp)、[配置与轨迹输出](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/src/BasicSystem.cpp)、[CI](https://github.com/Jiaoyang-Li/RHCR/blob/d009a3bd716419b0d6c04aead9dbca1720c012da/.github/workflows/test_macos.yml)。

libMultiRobotPlanning 的 CI 在 Ubuntu 上分别构建 Release/Debug 并运行 `make run-test`；其 SIPP 测试核验到达位置和时间，多车测试包括交换位置和部分车辆已在终点。见 [CI](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/.github/workflows/build.yml)、[SIPP 测试](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/test/test_sipp.py)、[多车 SIPP 测试](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/test/test_mapf_prioritized_sipp.py)。

## 2. 适合本项目的工程取舍

当前课程项目需要一个可安装、可测试、可重复运行的 Python 程序，而不是多个互相复制状态定义的入口脚本。建议并采用下列职责边界；具体模块采用文件还是子包按代码量决定，避免为空目录增加层次。

| 位置 | 单一职责 | 依赖约束 |
|---|---|---|
| `src/agv/domain.py` | 场景、订单、地图合法性、任务生成 | 不依赖网页与实验报告 |
| `src/agv/simulation.py` | 唯一真实时间、车辆状态、任务归属、执行轨迹和候选提交 | 不读取未来订单给策略，不混入展示状态 |
| `src/agv/planning/` | A*、SIPP、取送路线、联合后缀修复 | 共用地图和 leg 契约，保留 A* 作参照 |
| `src/agv/dispatch/` | 贪心与可见订单匹配、调度循环 | 通过 observation 和环境公开接口工作 |
| `src/agv/evaluation/` | 指标、独立轨迹验解、失败诊断 | 验证依据实际路径/事件，不复用搜索内部判断 |
| `src/agv/experiments/` | 场景组合、固定种子、配对运行和汇总 | 保存具体配置与失败，避免只输出有利案例 |
| `src/agv/io/` | 场景读写、结果导出 | 保持输入/结果格式清晰 |
| `src/agv/web/` | 读取结果、展示轨迹、交互控制 | 界面不自行发明另一套仿真与算法 |
| `tests/unit/`、`tests/integration/` | 分别验证局部契约与跨模块流程 | 安装包后运行，不依赖当前工作目录偶然可导入 |
| `docs/`、`examples/`、`results/` | 说明、可复现输入、实际结果 | 历史报告标记历史版本，不覆盖成最新结论 |

这是本项目的结构设计，不是宣称参考仓库也使用完全相同的目录。相同职责只保留一个实现；旧路径若需要兼容，使用很薄的入口，不维护第二份算法。

构建配置应声明 Python 版本、包位置和统一 CLI；运行参数显式保存场景、种子、任务分配器、低层路径规划器、重规划周期、候选预算与版本。默认执行逻辑维持标准库依赖；画图和开发检查作为可选依赖。固定小例与独立验证进入 CI，耗时配对实验单独执行。不能因为另一个科研仓库缺少某类检查，就删掉本项目已有的碰撞或服务验证。

## 3. SIPP 原论文及本项目的改造边界

原始论文是 Mike Phillips 与 Maxim Likhachev，*SIPP: Safe Interval Path Planning for Dynamic Environments*，ICRA 2011，5628–5635。论文以“位置配置、安全时间区间”识别搜索状态，把到达时刻作为该状态的标签，以减少逐时刻状态。其论证使用能够原地等待、以时间为代价、忽略惯性约束等条件。见 [作者原文](https://www.cs.cmu.edu/~maxim/files/sipp_icra11.pdf)、[作者研究机构记录](https://publications.ri.cmu.edu/sipp-safe-interval-path-planning-for-dynamic-environments)、[实验室出版记录](https://sbpl.github.io/publications/sipp-icra11/)。

本项目在单位步长、四邻格移动/等待、离散时刻模型中使用这一思想，增加服务连续占位、服务禁用时段、有限 horizon、对向交换约束，并继续输出逐步轨迹。这是针对现有 leg 接口的实现，未复制作者仓库代码，也未实现 SIPPS 的软冲突最小化机制。

低层 SIPP 改善的是给定其他车辆预约时单段搜索的状态表示；它不会自动更换任务分配、协调车辆优先级或保证全车队最优。即使每一段都最早完成，取货—送货—返回的逐段拼接与在线调度仍保留已有局限。

## 4. 当前模型中可以合并哪些状态

以下是本项目模型下的正确性分析。

对某格 `p`，将 `[now, horizon]` 内未被顶点预约占用的时刻分割为最大连续闭区间 `[lo, hi]`。搜索键是 `(p, interval_id)`，标签是已知最早到达时刻 `arrival`。

如果同一状态存在两次到达 `a <= b`，从 `a` 到 `b` 都在同一安全区间内，那么先到达者可以原地等到 `b`，再执行后到达者的全部后续动作。因此以完成时间为目标时，后到达标签不提供额外可达性，可被支配。这一论证依赖：

- 原地等待被允许，代价正好是耗时。
- 状态中没有尚未表示的速度、朝向、载荷阶段、能量等会影响可行动作的变量。
- 被合并标签属于同一个连续安全区间；不能跨越中间被占用的时刻等待。
- 动态预约在本次搜索期间固定，边约束在实际离开时刻单独检查。

若后续要在一次搜索中联合求取货和送货，则还需将任务阶段/目标序号和必要服务进度加入状态；不能仅用 `(cell, interval)` 把“已取货”和“未取货”合并。若引入等待与移动不同的成本、加减速、电池限制，也要重新检查支配条件。

## 5. 边、服务和时间端点的必需约束

### 5.1 从源区间转移到目标区间

设车辆在源格 `p` 的安全区间中于 `arrival` 到达，源区间末端为 `upper`，目标格 `q` 区间为 `[lower, end]`。单位移动的候选到达时刻满足：

```text
enter >= max(arrival + 1, lower)
enter <= end
enter - 1 <= upper
(enter - 1, q, p) not in existing_edges
```

第三项允许车辆在源格安全的最后一刻离开，下一刻进入目标格；不能误写成 `enter <= upper`，也不能允许在源区间结束后继续等待。最后一项检查别车的 `q -> p` 对向运动，顶点安全区间本身不能排除交换冲突。

现有实现从最早候选开始，跳过被逆向边占用的出发时刻；超过任一界限便放弃该目标区间。对每个目标区间只保留可达的最早标签。启发式沿用忽略动态预约的地图最短距离，不能因道路拥堵擅自加上可能高估的常数来宣称仍精确。

工程参考也需要核对碰撞语义：w9 的预约表文档明确把边预约和顶点预约分开，且目标尾部占位需要显式设置；其不同 SpaceTimeAStar 接口还区分永久停留与到达即消失。见 [ReservationTable 文档](https://w9-pathfinding.readthedocs.io/stable/mapf/ReservationTable.html)、[SpaceTimeAStar 文档](https://w9-pathfinding.readthedocs.io/stable/mapf/SpaceTimeAStar.html)。

libMultiRobotPlanning 的通用 SIPP 通过 `isCommandValid()` 把运动检查交给环境；此次读取的优先级示例只计算最早到达，未在该回调中实现本项目的逆向边预约检查。因此不能直接照搬这一示例便宣称满足当前交换冲突模型。见 [通用 SIPP](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/include/libMultiRobotPlanning/sipp.hpp)、[该示例](https://github.com/whoenig/libMultiRobotPlanning/blob/4c75fa20c435c440d8b6bd6dc81668ddc7296ba0/example/mapf_prioritized_sipp.cpp)。

### 5.2 连续服务不能只检查到达格

服务持续 `d` 个时间区间，若从 `begin` 开始，则车辆位置在闭区间 `[begin, begin+d]` 的所有离散时刻均为目标格，服务动作覆盖半开区间 `[begin, begin+d)`。因此：

```text
begin >= arrival
begin + d <= safe_interval.end
all(t not in service_blocked for t in range(begin, begin+d))
```

若最早到达时服务资源正被禁用，但同一安全区间稍后能开始服务，应允许在目标格等候；不能因此删掉整个区间。若本区间太短不能容纳服务，车辆可能需要先离开目标格，在下一个安全区间重新进入，不能把“到过目标”直接当作完成。

`service_blocked` 是服务动作限制，不是顶点占位：禁止某时段装货不代表车辆连这个格都不能经过。已经启动的服务由上层冻结剩余段，不能通过换低层搜索器中断或倒退任务阶段。

### 5.3 搜索压缩与结果展开要分开

SIPP 可以一次把等待跳过几十步，但环境、独立验证器和网页仍消费逐时刻坐标。回溯必须在父格补齐隐式等待，再添加移动和目标服务重复格。只有关键点的路线会低估等待、遗漏占位，使碰撞检查与显示时间失真。MAPF-LNS 作者实现也在回溯时补入父位置等待，见 [其 `SIPP.cpp` 的 `updatePath`](https://github.com/Jiaoyang-Li/MAPF-LNS/blob/95785de66f8fbdb91fed871e1a56c8c563f39b1f/src/SIPP.cpp)。

## 6. 本地审查与实际验证边界

本次已阅读 `src/agv/planning/sipp.py`、`astar.py` 和 `tests/unit/test_sipp.py`。实现使用区间最早到达标签，单独检查逆向边，并在目标区间搜索合法服务开始时刻；保留当前可行终点上界，按一致的时间下界继续/终止搜索；输出时展开等待。审查时未发现当前离散单位时间契约内的必须修复问题。

除项目测试外，本次独立执行了 12,000 个小图差分实例，以现有逐时刻 A* 为参照，比较是否有解及最早完成路线长度。额外逐点检查顶点预约、逐边检查逆向预约、验证相邻移动与服务后缀、服务禁用时段和 horizon。随机条件包括：

- 2–5 列、1–4 行，随机静态障碍和可能断连地图。
- 起点可以等于目标，开始时刻可以正好等于 horizon。
- 0–5 步服务，随机顶点禁用时刻、随机相邻有向边预约、随机服务禁用时段。

12,000 例全部匹配并通过路径检查。这验证了较广的有限样本，并非穷尽证明，也不是标准 MAPF benchmark 的算法排名。该额外检查是本次终端运行的审查证据；可长期复跑的差分测试以仓库测试文件为准。

没有用这次验证程序的运行时间声称 SIPP 比 A* 快。性能评估应在同一任务分配器、同一重规划设置、相同种子与订单下分别替换 A*/SIPP，报告总运行耗时、搜索调用数、展开/生成状态数、任务完成率、流动时间与 makespan。长等待合成例可以解释状态压缩，却不足以代表常规地图全部工作负载。区间构造、预约集合扫描、完整候选验证也有成本，短路线/低拥堵场景可能没有加速。

## 7. 后续修改应保留的验收点

1. 独立验解继续检查整个已执行历史和完整未来候选，低层优化不能跳过服务、冲突和历史指标核验。
2. SIPP 与 A* 共用 leg 输入输出契约，但差分测试不要复用 SIPP 的区间函数判断答案。
3. 保留 blocked start、goal/start 相同、horizon 边界、服务等待、目标离开重进、逆边强制等待的显式例子。
4. 多车优先级修复仍是有限候选启发式；低层精确最早完成不改变其无全局最优保证的边界。
5. 把场景、配置、版本和测量口径与结果一起保存；历史改善百分比不作为重构后自动成立的新结果。

## 8. 公开仓库地图、许可与训练数据边界

### 8.1 数据来源与适合的地图

Moving AI Lab 的 [官方 MAPF 页面](https://movingai.com/benchmarks/mapf.html) 提供地图及起终点场景；[下载目录](https://movingai.com/benchmarks/mapf/index.html) 列出尺寸和可通行状态数。当前模型只有少量车辆、在线取送与服务时间，不需要先引入数万格仓库。

| 官方地图 | 宽×高 / 可通行格 | 当前建议 |
|---|---|---|
| `warehouse-10-20-10-2-1.map` | 161×63 / 5,699 | 首选仓库来源；原图仍明显大于当前课程示例，可用预先固定的小裁剪区域。 |
| `warehouse-10-20-10-2-2.map` | 170×84 / 9,776 | 可作为不同巷道宽度来源或额外地图留出测试；不是同一张图的另一个随机种子。 |
| `warehouse-20-40-10-2-1.map` | 321×123 / 22,599 | 当前无需优先使用。 |
| `warehouse-20-40-10-2-2.map` | 340×164 / 38,756 | 当前无需优先使用。 |

上述官方仓库集中没有原生 25×19 的小仓库。可用于解析/搜索 smoke test 的官方小图包括 `empty-8-8`、`empty-16-16`；它们没有货架语义，不能仅因为较小就冒充仓库训练样本。尺寸依据均为 [官方列表](https://movingai.com/benchmarks/mapf/index.html)。

适合后续实际获取的精确链接：

- [161×63 仓库地图 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-1.map.zip)。
- [对应 25 组 random 起终点场景 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-1.map-scen-random.zip)。
- [170×84 仓库地图 ZIP](https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-2.map.zip)。

本研究步骤只核对官方网页链接及元数据，没有下载或改写项目数据文件。

### 8.2 格式及转换需要明确的语义

地图头依次为 `type octile`、`height H`、`width W`、`map`，之后是 ASCII 行，左上角为 `(0,0)`。`.`/`G` 是可通行地形，`@`/`O` 是边界或阻塞，`T` 是不可通行树木；其他地形字符带有单独通行语义，不能静默全部当作普通地面。场景文件先写 `version 1` 或 `version 1.0`，之后每行 9 列：bucket、地图名、宽、高、起点 x/y、终点 x/y、optimal length。见 [官方格式说明](https://movingai.com/benchmarks/formats.html)。

原 `.scen` 是一次性起终点对，**不包含在线 release、货架标识、装卸服务、停车位或订单流**。官方 MAPF 页面建议逐步增加所用起终点对数量直到达到求解资源上限；它并不是 MAPD 订单训练集。见 [官方 benchmark 使用说明](https://movingai.com/benchmarks/mapf.html)。

若裁剪原图并补充这些字段，应称为“基于 MovingAI 仓库几何生成的 MAPD 派生模拟数据”。记录原图名、原始内容 SHA-256、裁剪框 `(x0,y0,width,height)`、坐标变换、障碍到合成货架的规则、停车位与取送点选择、服务时间、订单生成种子。被阻塞的原始格只说明几何障碍，不天然就是具有业务含义的货架；外墙不应直接成为可下单货架。新增停车位规则也可能阻断通道，转换后重新做连通性与任务可完成性检查。

裁剪、增加服务与任务流后，不使用原 `.scen` 的 `optimal length` 作为新任务标签；重新按本项目四邻移动及服务模型求候选成本。结果不能写成官方 MAPF benchmark 排名，也不能直接与原论文数百辆车的一次性 MAPF 实验横比。

### 8.3 数据许可和发布记录

[官方 MAPF 页面](https://movingai.com/benchmarks/mapf.html) 与 [总入口](https://movingai.com/benchmarks/) 声明数据采用 Open Data Commons Attribution License；链接指向 [ODC-By v1.0 正文](https://opendatacommons.org/licenses/by/1-0/)。该正文第 4 节要求公开传递数据库或衍生数据库时保留许可/URI和权利声明；公开使用产出物也提供关联的来源和许可署名。许可同时说明其范围与数据库中独立内容权利的区别，因此不把数据声明扩展成任意第三方素材的通用授权。

实际发布建议在数据目录保留 `NOTICE` 或说明文件，写明 Moving AI Lab、具体来源链接、ODC-By URI、获取日期、原始与派生内容的区分；报告与相关演示注明使用该来源。代码许可证与第三方数据声明分开。使用官方数据的论文引用可按 [官方要求](https://movingai.com/benchmarks/mapf.html) 引用 Stern 等，2019，*Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks*。

### 8.4 可解释候选排序模型的评估范围

如果用这些地图训练候选优先顺序排序器，标签应来自训练场景上实际候选求解得到的可行性和成本变化，特征只包含当前可见订单、地图和车辆状态。训练区域、验证区域、测试区域预先固定且不相交，并使用各自独立的任务种子；不得先根据测试效果挑区域或调参数。来自同一规律仓库图的区域仍可能共享货架重复模式，因此区域留出只支持这一来源内的空间泛化，不能冒称对未知仓库的泛化。

与未训练顺序对比时，保持同样的候选数量和规划预算，报告未见区域上的真实仿真指标及失败率。线性或树式排序器的参数/特征贡献可以解释排序倾向，但是否真正减少拥堵要用被接受重规划的路线和等待变化验证。这里的数据使用方案尚不构成训练完成或效果提升的证据，也不表示取得了任何私密数据。
