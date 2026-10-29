# 架构审核方案的落实与可选扩展

本轮依据《AGV架构审核与重构方案.md》对照现有实现，保留已完成的分层，继续补实验复用、规划缓存与可组合参数。输入文档是设计参考，预期收益是待验证假设；不会为达到阈值而修改业务规则、独立验解或冻结结果。

## 结构与实施取舍

`core → warehouse/rules/orders → world → planning → policy → runner/registry → application` 的依赖方向已由架构门禁检查。静态场景与规则、订单发布器、唯一可变世界、命令网关、派单/定位/修复流水线、执行循环和独立验解均有明确所有者。历史导入路径保留薄适配层，避免外部调用突然失效；它们不再拥有另一套执行循环。

| 方案内容 | 本轮处理 | 理由与边界 |
|---|---|---|
| PR0–9：金标准、分层内核、三段策略、单一 runner、规则对象 | 沿用并再次完整回归 | 已完成的结构见 [架构合同](architecture.md) 和 [首轮重构证据](architecture-refactor.md)，不为目录变化重复搬动 |
| PR10：实验缓存与进程并行 | 实现 | 一个场景内保留配对与轮转顺序，场景间进程隔离；结果缓存仍重新验解 |
| PR11：静态距离共享 | 实现、默认使用 | 懒计算只读 BFS 表，有界共享；逐步轨迹和实际路由调用计数保持一致 |
| PR11：动态 ETA 缓存 | 实现、默认关闭 | 精确时刻与预约签名；标准小场景未测到命中，不宣称 40% 调用下降 |
| PR12：车辆负载/卸货口负载线性加权 | 数学审计后未加入 | 完整匹配时分别是行常数、列常数；当前空闲候选车没有未完成的已承诺运货任务 |
| PR13：需求窗口、重排周期、热区冗余、利用率保护 | 实现为独立可选参数，实验决定是否采用 | 不放宽合法待命格、割点、服务区与交通让路规则 |
| PR14：BCRD 确定性预算 | 接入 SolverSpec 并实验 | 直接使用真实调用/扩展/步数预算与合法贪心回退，先不拟合机器相关 CPU 模型 |
| PR14：自适应 top-k 剪枝 | 暂不启用 | 需要完整候选召回率与 F 损失证据，不能把剪枝当作纯性能等价修改 |
| PR15：局部窗口联合修复 | 保留现有完整后缀修复、未新增窗口算法 | 当前修复验解包括完整未来轨迹；仅验证 ±k 窗口会遗漏拼接边界和窗外冲突 |
| PR16：故障后的任务迁移 | 不混入当前业务模型 | 已承诺订单不可撤销/改变车辆归属；任意故障下仍保证完成也不可成立，例如所有车同时不可用 |

PR12 的具体原因：对于固定车辆集合 V 和订单集合 J 的完整匹配 π，
`Σ_v [c(v,π(v)) + α L(v) + β C(π(v))] = Σ_v c(v,π(v)) + α Σ_v L(v) + β Σ_j C(j)`。
后两项不随配对变化。矩形匹配中列项可能改变先选哪些订单，但这不同于改善车辆—订单配对；共享同一卸货口时该项也不能区分订单。拥堵应进入车辆、订单、时刻相关的真实 ETA 或候选 rollout，而非无效常数项。

## 新的模块接口

- `runner/batch.py`：`BatchTask(seed, payload)` 与 `run_batch(tasks, worker, workers=N)`。串行与 spawn 进程池使用相同任务接口，按输入顺序返回；异常向上传递，每任务显式设随机种子，串行结束恢复调用者随机状态。
- `experiments/cache.py`：规范化身份、内容哈希、本地原子结果缓存。完整场景、SolverSpec、工况、种子、源码/模型/网页资源与 Python 运行时进入 key；默认缓存目录位于项目外。损坏、不匹配或验解失败后回源计算；源文件改变时不发布本轮待写的缓存。
- `planning/distance.py`：静态 BFS 表跨实例懒共享，全局 LRU 128、每实例引用 LRU 64。地图、车辆 home 权限、终端卸货口规则及 horizon 隔离。只读距离表深拷贝可安全共享，router 的计数、附加字段、世界可变状态仍独立复制。
- `planning/cache.py`：`EtaCache(capacity)`，使用精确出发时刻、位置、任务、合法取货候选和排除本车后的未来预约签名，不使用粗时间桶。hit/miss/失效/淘汰单独计数；`decision_routing_stats` 始终只记录真正执行的路由调用。
- `registry.py`：不可变 `AssignSpec` 增加 `eta_cache_capacity=0` 与 `route_budget/expansion_budget/step_budget=None`；`IdleSpec` 增加 `stat_window=None`、`rebalance_period=None`、`hotspot_zones=0`、`protect_utilization=None`。无效类型、范围与不支持的组合在构造时拒绝。旧名称、默认值和输出字段保持兼容。
- `experiments/architecture_options.py`：独立的新实验协议，按 Spec 组合候选，无需为未验证候选注册公共算法名。运行/验解/评分失败均保留行；拒绝覆盖已有结果。

定位的短统计窗口只包含已经观察到且仍在窗口内的订单；重排周期独立配置，新空闲事件仍可触发定位。热区只增加一个合法停车名额。利用率保护仅限制自愿重定位，不能覆盖内核的预约冲突让路，也不保护在途、非法或已超容量的位置。

## 运行与复现

正式 V9.1 基准保持原先 200–219 留出协议，不偷换历史冻结集：

```bash
agv benchmark-v91 --protocol examples/experiments/v91-development.json \
  --output runs/cache-cold --workers 2
agv benchmark-v91 --protocol examples/experiments/v91-development.json \
  --output runs/cache-warm --workers 2
agv benchmark-v91 --protocol examples/experiments/v91-development.json \
  --output runs/fresh-timing --workers 2 --no-cache
```

`--cache-dir` 可指定目录，`--refresh` 强制重算并刷新；`--no-cache` 禁用读取和写入。缓存 CPU/wall 保留原测量值并标记 `timing_origin=cached`，不属于新的运行速度。完整性哈希与独立验解不能证明某条合法轨迹一定由所声明算法生成，缓存按本机可信数据使用。

新架构选项使用开发种子 10–19，冻结配置与源码后再运行 30–49；与历史 200–219 协议分开：

```bash
python -m agv.experiments.architecture_options runs/options-dev.json \
  --config results/architecture-options-2026/positioning-final-config.json --workers 2
python -m agv.experiments.architecture_options runs/options-freeze.json \
  --config results/architecture-options-2026/positioning-final-config.json --freeze
python -m agv.experiments.architecture_options runs/options-holdout.json \
  --config results/architecture-options-2026/positioning-final-config.json \
  --split holdout --frozen runs/options-freeze.json --workers 2
```

结果与复现记录见 [本轮证据目录](../results/architecture-options-2026/README.md)。F 越低越好，改善率定义为 `100×(对照F−候选F)/对照F`。配对以同地图、同工况、同种子为单位；CPU 仅包含原始求解，不包含离线 A* 参照和最终验解。并发进程存在资源竞争，单轮 CPU 比值不能作为跨机器结论。

## 最终验证与采用决定

最终345项测试全部通过，新增46项覆盖缓存、深拷贝、进程顺序、配置适配、失败保留与冻结协议。完整580次金标准回放全部通过独立验解，除真实计时外规范化完整结果零差异，回放前后源码一致。独立验解器与 `origin/main` 逐字节一致；依赖门禁、148文件格式检查、lock检查及源码目录外安装验证通过。完整证据见 [verification.json](../results/architecture-options-2026/verification.json)。

结果缓存最终48/48命中，总墙时50.012→13.973秒，约3.579倍；热跑耗时仍为冷跑27.94%，未达文档≤5%目标。共享静态距离表在单种子三工况的热复用CPU倍率为1.131–1.173倍，54次运行的完整轨迹/F一致。两项均为实现/实验开销优化；动态ETA在标准小场景命中0、真实调用下降0%，继续默认关闭。测量有背景并发负载，不能将绝对时间与早期报告直接横比。

冻结后的新留出集为4档地图×3工况×20种子，三策略共720次，全部有效。以下对照都是已有 `sipp_position_delay_dispatch`，每个新选项有240组同场景配对；F改善为正表示更好，CPU比为候选/对照：

| 留出策略 | 平均F改善率（%）及95%配对区间 | 平均CPU比 | P90变差场景 | 平均空驶增量 |
|---|---|---:|---:|---:|
| 仅周期改为500 | +0.083，[-0.059, +0.230] | 0.882 | 21/240 | +13.09格 |
| 周期500＋窗口100 | -0.086，[-0.309, +0.131] | 0.893 | 30/240 | +27.72格 |

长周期在稀疏组的平均CPU比为0.720（约节省28.0%），密集静态组轨迹/F完全相同。少做定位匹配能省计算；停车目标保持更久，也可能使下一单取货路程更长，符合实测空驶增加。短窗口丢弃较早的已见需求，尤其共享批量工况没有显示收益：F平均变差0.342%，区间仍跨零。整体F差异均不足以支持稳定质量改进，且个别响应尾部恶化，所以不改默认算法或现有参数、不注册新公共算法名。

开发筛选10–12还比较了热区冗余/利用率保护以及BCRD调用预算。新定位项相对已有定位的F改善区间均跨零；压缩到120次调用、2候选时，在3个密集开发场景只保留约25%的原BCRD平均F收益，CPU仍约为同场景贪心的2.99倍，没有达到“保留80%收益、CPU≤1.3倍”目标。因此没有进一步拟合CPU模型或启用top-k剪枝。它们只保留可测试的显式参数接口；开发筛选不作为新留出收益结论。

本轮采用的是经过轨迹等价验证的静态共享、经过重新验解的实验缓存，以及严格配置和实验边界。故障迁移需另设业务合同与验解规则；窗口修复需证明完整后缀和边界安全，均未混入当前版本。
