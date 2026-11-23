# V9.1 理论基础：可证松弛下界与安全待命选点分析

日期：2026-10-17

本文给出 V9.1 阶段引入的**可证离线松弛下界**的数学推导与单元测试验证，并梳理安全待命选点机制的文献依据。松弛下界用于离线诊断现有策略相对理想无冲突极限的差距，各策略的实际调度表现见 [V9.1 优化实验报告](../v91-optimization.md)。

## 1. 文献依据

1. **Ma, Li, Kumar & Koenig (AAMAS 2017)**, *Lifelong Multi-Agent Path Finding for Online Pickup and Delivery Tasks*（[作者原文](https://jiaoyangli.me/files/2017-AAMAS.pdf) §3.2 Definition 1, §4.1）：定义 well-formed MAPD 要求存在足够多的非任务端点且任意端点间路径不穿过其他端点；Token Passing 在空闲车阻挡待执行任务卸货点时主动避让。这一思想直接指导本项目在待命选点阶段排除业务端点、入口邻格、割点与窄通道。
2. **Treleaven, Pavone & Frazzoli (TAC 2013 / 2012 预印本)**, *Asymptotically Optimal Algorithms for Pickup and Delivery Problems with Application to Large-Scale Transportation Systems*（[实验室原文](https://stanfordasl.github.io/wp-content/papercite-data/pdf/Treleaven.Pavone.ea.TAC13.pdf) Theorem 5.4, Remark 5.5, p. 18）：将取送货巡回拆分为载货段与“卸货 → 下一取货”空驶连接段，指出连接段构成二分匹配且总长受限于最优匹配值。本项目借鉴该映射思想，并将其推广至含多专属停车位 `H` 与单排双侧取货约束的离散网格模型。
3. **Frieze & Sorkin**, *The Probabilistic Relationship Between the Assignment and Asymmetric Traveling Salesman Problems*（[作者原文](https://www.math.cmu.edu/~af1p/Texfiles/atsp.pdf) §1, pp. 1–2）：指出放松单环连通性约束后，一般指派最优值严格小于等于巡回最优值，为采用闭合指派构造总里程下界提供经典组合优化依据。

## 2. 常见松弛公式的修正

在推导严格下界前，先通过极小反例修正两类容易出错的直觉公式：

- **单任务时间下界的发布重叠问题**：直觉公式 `release + distance(initial_home, pickup) + loading + loaded + unloading` 可能高估真实最优完工时刻。因为车辆可在订单发布前提前移动至取货点，或直接由上一单卸货口驶来。反例：初始距取货点 2 步，订单在 `t = 50` 发布，装货 1 步、载货 5 步、卸货 1 步；允许提前就位的车辆可在 `t = 2` 到达并等待至 `t = 50` 开始服务，于 `t = 57` 完成，而直觉公式算出 `50 + 2 + 1 + 5 + 1 = 59 > 57`。因此必须取 `max(50, 2) + 1 + 5 + 1 = 57`。
- **有限任务链的起终点闭合问题**：简单使用 `sum(loaded_distances) + n×n(delivery → pickup)` 完美匹配会强制构造任务闭合环（例如仅有 1 张订单时强行加入 `delivery → pickup` 边），反而可能超过真实 `Home → pickup → delivery → Home` 长度。正确做法是将每辆车的初始与最终 `Home` 显式纳入指派方阵，或在计算完工前工作量界时采用开放链矩形指派。

## 3. 接口设计与静态距离定义

下界模块实现于 `agv.evaluation.bounds.lower_bounds(scenario)`，仅用于离线完整场景诊断，返回 `T`、`R`、`D` 下界及分项 `details`（严格与在线 `observe()`、派单逻辑及评分分母隔离）。

记 `d_v(a, b)` 为车辆 `v` 的静态最短路距离（通过现有 `Router` 反向 BFS 计算，保留静态障碍、禁止进入他车 `H` 以及 `D` 站仅作为交付终点的语义，放松多车避碰、预约与层序锁）。由于车辆在执行第 `j` 单之前可能已经合法访问并离开过其他 `D` 站，计算从初始 `H_v` 到第 `j` 单取货侧的时间下界时，采用进一步允许途经其他 `D` 站格的距离 `d^0_v(H_v, q)`，以确保松弛在数学上绝对严格；第一单与相邻两单间的连接则继续使用 `d_v`。同时，每单的接近距离与载货距离始终绑定于同一对合法 `(vehicle, pickup_side)`，避免将不同取货侧的最小段错误拼接。

## 4. 完工时间 `T` 与平均响应 `R` 的下界证明

对订单 `j`，令发布时刻为 `r_j`，总服务时长为 `s_j = pickup_service + delivery_service`，合法取货侧集合为 `Q_j`。定义单任务最早完工下界：

```text
c_j = min_(v, q ∈ Q_j) [max(r_j, d^0_v(H_v, q)) + s_j + d_v(q, D_j)]
T_individual = max_j c_j
R_LB = mean_j (c_j - r_j)
```

**有效性**：任意合法可行解中，承接订单 `j` 的车辆 `v` 从自身初始 `H_v` 抵达实际取货侧 `q` 至少需 `d^0_v(H_v, q)` 步，且装货不早于 `r_j`，随后必须完成 `s_j` 步服务与至少 `d_v(q, D_j)` 步载货行驶。因此实际完工时刻不小于 `c_j`，逐单取最大值与均值分别给出有效的 `T_individual` 与 `R_LB`。

进一步构造**开放链工作量下界**：以全部 `m` 个初始 `H` 与 `n` 个任务卸货口作为左部前驱节点，为 `n` 个任务分配互不相同的前驱（禁止自环），边权为对应前驱到任务取货侧再至该单卸货口的最短移动步数。任何合法多车任务链均构成该矩形指派的一个可行匹配，因此最优矩形指派值 `D_prefix` 不高于最后一单卸货前的实际总移动步数（不含最终返库）。结合最多 `m` 辆车并行作业，得到：

```text
T_workload = ceil((D_prefix + sum_j s_j) / m)
T_LB = max(T_individual, T_workload)
```

由于最终返库可能晚于最后卸货，此处严格使用不含返库的 `D_prefix` 参与 `T_workload` 计算。

## 5. 总移动距离 `D` 的闭合指派下界证明

完整解要求每辆车最终返回自身 `H`，总里程 `D` 包含空驶、载货、重定位与最终返库。构造 `(n + m) × (n + m)` 闭合指派方阵：左部为 `m` 个初始 `H` 与 `n` 个任务卸货口，右部为 `n` 个任务与 `m` 个结束 `H`：

| 有向边类型 | 边权定义 |
|---|---|
| 初始 `H_v` → 任务 `j` | `min_(q ∈ Q_j) [d_v(H_v, q) + d_v(q, D_j)]` |
| 任务 `i` → 任务 `j`（`i ≠ j`） | `min_(v, q ∈ Q_j) [d_v(D_i, q) + d_v(q, D_j)]` |
| 任务 `i` → 结束 `H_v` | `d_v(D_i, H_v)` |
| 初始 `H_v` → 自身结束 `H_v` | `0`（表示该车全程空闲） |
| 任务自环、跨车初始 `H` → 结束 `H` | 禁止（无穷大） |

**有效性**：任意完整合法解中，每辆车的任务序列 `H_v → j_1 → j_2 → … → j_k → H_v`（空闲车为 `H_v → H_v`）在方阵中精确对应一个完美指派；且每条边的静态最短路权值均不高于实际包含绕行或重定位的行驶距离。因此由纯 Python 矩形 Hungarian 算法求得的整数最小权完美指派值 `D_LB` 严格小于等于任意完整可行解的总移动步数 `D`。松弛解中可能出现的纯任务子环或相邻边跨车切换只会进一步拉低数值，始终保持下界合法性；空任务场景三项下界均为 0，无有限指派时显式报错。

## 6. 下界诊断解读与验证

在分析实验结果时，可分别计算相对松弛差距 `(actual - lower_bound) / lower_bound`（分母为 0 时跳过），并在需要综合 `F` 下界时使用**同一场景既有参考分母**对 `(T_LB, R_LB, D_LB)` 加权。由于下界放松了动态避碰、货架层序锁与多车链条一致性，差距反映的是理论松弛空间与物理约束开销之和，结合交通等待指标可以有效定位核心瓶颈（如 Stage 0 诊断出响应差距大而交通等待小，从而明确优先投入派单与待命选点）。

在待命选点侧，本项目综合上述非阻塞原则与启发式权衡：过滤业务端点、割点与窄通道后，仅基于当前可见历史需求热度与静态最短路分配带区域容量和迟滞惩罚的安全待命点，同时完整计入重定位空驶并保留随时可中断的返库后缀。

**单元测试验证**：`tests/unit/test_bounds.py` 涵盖 7 项核心验证——障碍绕行与末次返库手算单例、晚发布防重复叠加验证、单入边同取货侧一致性、空订单流、含禁边随机小矩阵上矩形 Hungarian 与穷举的精确一致、3 单 2 车全排列穷举验证 `T/R/D` 下界严格有效，以及两例 V9.1 八层真实 SIPP 全程执行与独立验解。验证命令：

```sh
.venv/bin/python -m unittest tests.unit.test_bounds -v
.venv/bin/ruff check src/agv/evaluation/bounds.py tests/unit/test_bounds.py
.venv/bin/ruff format --check src/agv/evaluation/bounds.py tests/unit/test_bounds.py
```
