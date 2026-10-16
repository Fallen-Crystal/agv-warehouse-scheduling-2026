# BCRD 可见状态影子执行合同

BCRD 在正式派单前比较有序批次。影子模块只接收 `Environment.observe()` 的返回值，复用真实执行器与路径规划器，预测当前已发布任务的后果。它不接收完整场景、真实环境对象、生成种子或离线评分分母。

实现位于 [`dispatch/shadow.py`](../src/agv/dispatch/shadow.py)，定向回归位于 [`test_bcrd_shadow.py`](../tests/unit/test_bcrd_shadow.py)。本合同描述已实现的接口及限制，不承诺多车全局最优或硬实时。

## 从观测恢复执行状态

```python
from agv.dispatch.shadow import ShadowState

shadow = ShadowState.from_observation(observation, router_kind="sipp")
preview = shadow.preview(
    [(vehicle_id, task_id)],
    depth=None,
    budget={"max_route_calls": 120, "max_steps": 10000},
)
```

`from_observation` 从静态 `map`、当前 `time/horizon`、已发布 `pending`、车辆的 `active_task` 与承诺路线构造独立状态。任务坐标归一为元组，保留任务的层号、发布时间和服务时长。它拒绝观测中尚未发布的任务、重复任务、缺失的活动任务身份、起点不等于当前位置的路线，以及不返回车辆专属停车位的承诺后缀。

每次预览创建一个仅含可见任务的 `Environment`，然后在影子模块边界内恢复其私有执行状态：

| 执行字段 | 可见来源 | 必须保留的语义 |
|---|---|---|
| `time` | 观测时刻 | 路线记录继续使用绝对时间 |
| `_jobs/_scenario.tasks` | `pending + active_task` | 无未来任务；不虚构已完成任务的发布时间 |
| `_plans` | `committed_path` 或 `return_path` | 所有活动预约与正在回库的预约保持完整 |
| `_active/_records/_assigned` | 活动车辆的任务与 `route_record` | 已接单归属和既有服务区间不变 |
| `_paths/_interval_states` | 当前车辆位置及随后预览执行 | 只保存观测时刻之后的预测轨迹 |

这里使用私有字段是为了恢复真实执行器已有语义，限制在 `shadow.py` 内；候选生成器和在线调度器不读取真实环境内部状态。没有克隆含未来任务的真实 `Environment`，也没有修改 `planning/`、`warehouse/` 或原评分器。

历史已完成记录不再持有未来取货锁，但后续策略仍可看到观测已经公开的 `completed` 和旧回库 `route_record`。这些历史常数不进入候选的可变代价。正在回库的路径始终参与预约，即使车辆已经可以接下一单。

## 试派、滚动与路径含义

初始批次原样送入真实 `Environment.assign()`。其顺序决定逐对建立预约的先后；非法批次仍由执行器整批拒绝，合法但规划失败的配对保留真实失败反馈。V4 层序、同面锁、连续装卸、专用 D 站及合法退出均由原执行器和真实 A*/SIPP 处理。

后续滚动遵循“先提交、再前进一步”的真实驱动节奏：初始动作在时刻 `t` 提交，下一次后续政策调用从 `t+1` 开始。默认精确跳过必为空动作的区间：全车忙碌时推进至最早卸货完成，全部可见任务已接单时推进至最后回库；`Environment.advance(delta)` 仍记录每一步。存在可用车与未派任务时逐步运行，自定义后续政策也始终逐步调用。`event_driven=False` 保留逐步对照。`depth` 限制的是非空后续批次数，不代表二层分支搜索。

| `depth` | 已实现行为 |
|---|---|
| `None` | 使用统一后续政策滚动，直到已知世界结束、停滞、达到场景时限或耗尽预算 |
| `0` | 只试派初始动作，直接结算全部现有承诺后缀 |
| 正整数 `n` | 最多尝试 `n` 个非空后续派单批次，随后报告残余任务 |

默认后续政策保持原距离贪心顺序，再过滤 V4 同批同面资源冲突。无可用车辆或无合法待派任务时直接返回空批次，避免重复静态距离建模。调用者可以传入统一的 `rollout_policy(observation)`，各候选应使用相同政策和前瞻期限。

返回的 `paths` 从当前观测时刻开始，包含已经模拟的预览路径及模拟停止时仍承诺的后缀，终点仍为各车辆停车位。它通过 `past + plan[1:]` 拼接，不重复当前边界位置。路线记录中的 `assigned_at`、装卸时间仍为绝对时间。预览返回可独立修改的数据，不改变原观测、真实路线记录或真实环境。

## 结果与残余

| 字段 | 含义 |
|---|---|
| `valid` | 初始试派及所执行回放没有非法动作、初始规划失败或预算失败；合法深度截断可为真 |
| `completed` | 所有已知未完成任务已有完整合法完工预测，不要求已经逐步模拟至回库结束 |
| `exhausted/reason` | 区分预算、初始规划失败、停滞、时限与深度截断 |
| `feedback` | 初始动作的真实 `assign` 返回值 |
| `assignments` | 原活动任务及预览中新接任务的真实路线记录 |
| `predicted_T` | 这些任务预计卸货完成的最大绝对时刻 |
| `flow_sum/flow_times/mean_flow_time` | 这些任务的预计卸货完成时刻减原发布时间 |
| `additional_moves` | 从当前观测开始、包含当前承诺回库的全部预测移动步数 |
| `residual_count/residual_tasks` | 仍未派单的已知任务，不能当成已经完成或无代价 |
| `routing_stats/planning_failures` | 真正规划器计数与执行器失败记录 |
| `simulated_steps/decision_rounds` | 回放时间步数与非空后续批次数 |
| `cpu_seconds` | 本次预览内的进程 CPU 时间，含状态恢复与规划；不含先前构造 `ShadowState` 的时间 |

浅层预览可能 `valid=True, completed=False`。在线评分必须统一估计或惩罚所有残余，不可因为少派难单就得到虚假的低分。`valid=False` 的候选不得覆盖已验证保底动作。

非零时刻的 `predicted_T`、平均响应和新增移动仅描述已知未完成任务与未来路径。它们省略了已完成任务的历史贡献，也不使用未发布订单或场景参考分母，因此不是完整 V4 分数 `F`。正式效果须使用完整真实执行结果，经独立验解后由原离线评分器计算。

## 预算与可复现边界

预算字段为 `max_steps`、`max_route_calls`、`max_expanded`、`max_cpu_seconds`。未知字段、负数和无效类型被拒绝；默认最多模拟 10000 步，防止无时限场景或自定义后续政策无限循环。

- `max_route_calls` 在每次真实 `router.leg` 前检查，是路由调用次数的硬上限。
- `max_steps` 限制实际回放步数，不限制已经计算出来的承诺路径长度。
- 扩展量与 CPU 在单次 `leg` 前后检查，不打断搜索内部循环。因此单次 leg 可以越过软上限；耗尽后整个候选预测无效，不能称为硬实时控制。
- `max_cpu_seconds` 和 `cpu_seconds` 使用 `time.process_time()`；外层还应单独记录完整决策的墙钟与总 CPU，包含候选生成、状态构造和所有预览。
- 候选之间的总预算由调用方共享和扣减，不能给每个候选重新发放整轮预算。

不用 CPU 截断时，同一观测、批次、后续政策及计数预算产生确定的结果。`cpu_seconds` 本身不确定，应从字节一致性比较中剔除；CPU 上限附近的截断也可能随机器负载变化。正式复现应以确定的候选、路由调用和步数上限为主，单独报告 CPU 软限触发。

## 已覆盖的差分验证

18 项定向测试覆盖：A*/SIPP 有序批次的真实反馈与逐点未来路径；动态场景多个非零时刻；已经开始的装货与卸货；已完成但尚在回库的车辆；共享 D 与仅一个出口的 D；同面层序与整批原子拒绝；替换不可见未来任务后预测 JSON 一致；重复预览与真实环境不变；硬路由调用预算、软扩展/CPU 预算与步数预算；深度残余；有限时限规划失败。完整共享站回放还接受原独立轨迹验解器检查。新增事件/逐步模式差分逐字段比较预测、计数、完整内部路径与服务标签，涵盖深度、时限、计数预算及自定义政策；窄CPU软限因工作量不同不承诺同一截点。

```bash
python -m unittest tests.unit.test_bcrd_shadow -v
```

## 旧 V4 证据在源码增长后的复核

新增 BCRD 文件后，旧 `results/v4/manifest.json` 的 43 个测量源文件与当前工作树自然不同。默认 `verify_v4.py` 仍严格拒绝这种漂移，不自动忽略新增文件。

需要复核旧证据时，显式指定其历史源码提交，并把新审核结果写到独立路径：

```bash
python scripts/verify_v4.py --source-revision 8551943 --output runs/v4-historical-audit.json
```

该模式先解析到完整 Git 提交，再枚举 `src/agv/` 中全部受测后缀文件，对每个 Git blob 重建 SHA。历史树的完整文件集合和内容必须与旧清单完全相同，不能只检查清单中的部分文件。基线参考、场景生成与独立验解仍运行当前代码，以核对现有基线行为与旧测量兼容。输出分别记录历史来源提交和是否匹配当前源码，并检查审核期间当前代码没有变化。它不会重新计时全部 54 个候选实验，也不覆盖原 `review-validation.json`。

```bash
python -m unittest tests.unit.test_v4_historical_audit -v
```
