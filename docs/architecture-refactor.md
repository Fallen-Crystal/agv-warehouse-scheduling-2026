# 架构重构与验收记录（2026-10-20）

本次执行用户提供的《AGV 调度系统架构审核与重构方案》的结构迁移部分：拆清状态、规则、发布、规划、策略、求解循环和验解的职责，同时保留算法选择、业务规则、默认参数及结果格式。最终比较基线为文档指定的 `main@81dc59313898687be0e64ff9ba19b236a9f8dc06`，包含 PR #2 / #3 已合并的生命周期、返回历史、输入及独立验解修复。

## 实现范围

| 原职责或位置 | 当前实现 | 保持的合同 |
|---|---|---|
| `domain.py` 中任务与版本 | `core/model.py` | 不可变 Task、原字段/序列化、显式 Profile |
| `domain.py` 中场景与生成 | `warehouse/scenarios.py` | 输入校验、场景哈希、原生成顺序 |
| 散落的版本许可与结束判断 | `rules/profiles.py` | legacy / V4 / V9 / V9.1 四套执行合同 |
| 发布器直接写环境字段 | `orders/source.py`、`publisher.py` | 发布器独占关闭事件，不向策略透露未来订单 |
| `simulation.py` 实际执行 | `world/state.py` | 唯一状态推进；`tick` 不决定派单或待命 |
| assign / hold / reposition / replan 分散写状态 | `world/commands.py` | 校验后提交、已接受任务不可取消、失败保留安全后缀 |
| 每步切片未来路线 | `world/itinerary.py` | 不可变共享路径缓冲区、O(1) 游标推进 |
| 任务归属和执行记录 | `world/tasks.py` | TaskBook 单一存储、显式生命周期查询；旧私有名称仅为同对象别名 |
| 多处构造预约索引 | `world/reservations.py` | 唯一路线预约表、版本号、排除当前车辆的只读视图 |
| 每次复制静态地图 | `world/observation.py` | runner 用只读观测并共享冻结地图；旧 `observe()` 返回可编辑脱离副本 |
| 四个独立 solver 主循环 | `runner/run.py` | 统一观测→派单提交→定位/修复→待命→tick 顺序 |
| 分散算法配置与名字编码 | `registry.py` | frozen SolverSpec、合法 profile 声明、23 个旧算法名及顺序 |
| 策略和结果汇总混合 | `policy/`、`evaluation/execution.py` | 策略只消费观测；指标只读取脱离内核的执行 trace |
| ShadowState 恢复私有状态 | `world/restore.py`、`policy/forecast.py` | 只恢复已发布工作，共用 WorldState tick，预算和预测口径不变 |
| 静态 BFS 距离 | `planning/distance.py` | DistanceOracle 与 A*/SIPP 使用相同终端站/专属 Home 权限 |

`domain.py`、`simulation.py`、`dispatch/` 及原 planning 预约/重定位入口保留薄兼容导出，避免旧 CLI、网页、实验脚本和调用方因目录迁移失效。实现代码不再反向导入这些兼容层。CLI/Web/实验入口通过 registry / runner 编配；归档旧基线的兼容运行函数也只调用同一个 runner。

分配批次继续保持旧语义：先完整检查输入合法性，再按有序车辆—任务对逐对规划提交；个别规划失败以 feedback 报告，不能把它误称为整批全有或全无事务。

## 对审核方案的必要调整

1. **保留提交后的新观测。** 定位和联合修复必须看到已提交派单后的可用车辆及预约，不能机械压成每步仅一次观测。主循环复用只读静态地图，仍按原顺序取得必要的新状态。
2. **没有另造一个“第二内核”。** 审核稿未逐行阅读 ShadowState；原代码已经复用 Environment 执行语义。本次将可见观测恢复移到 world，以工厂参数从 runner 显式注入同一个内核；保留旧 ShadowState 导入作为适配器。
3. **快照共享静态数据并复制可变状态。** 实际实现不是通用持久化写时复制容器。地图与不可变行程可共享，任务记录、预约表、发布器和路由计数隔离。推演不复制真实环境内隐藏的未来任务，而是从公开观测重建。
4. **维持归档格式。** 行程采用游标缓冲区，TaskBook 显式提供生命周期查询，历史 route-record JSON 仍保留字典结构；本次没有把所有归档事件改成 Segment 序列。
5. **保持实验边界。** 不接入 IncrementalF，不开放定位+BCRD，不启用 top-k 匹配剪枝，也不新增主循环事件跳跃。它们属于会影响算法选择或轨迹的后续实验，不能混入“行为保持”的结构验收。BCRD 原有安全事件推进照旧。

## 依赖与状态写入门禁

```bash
.venv/bin/python scripts/check_architecture.py
```

AST 检查覆盖顶层/函数内导入、常见动态导入字面量、内核外私有路线/记录的直接赋值与容器修改、旧 solver 里的重复主循环、重复执行内核及预约实现。独立验解器禁止导入 world / planning / policy / runner / simulation。CI 中违规直接失败；独立 golden job 在每次 push / PR 上执行完整580次回放；负向单元测试验证门禁本身会拒绝错误结构。它是工程静态约束，不宣称能够识别 Python 任意反射或间接别名写入。

## 实际修复的回归风险

- 同一 Environment 跨地图 reset 后，待命几何缓存必须失效；以 100 步真实路径对照新建环境验证。
- 公开 `runner.run(spec, scenario)` 同样执行 profile 许可校验，不能绕过命名入口。
- SolverSpec 中会被输出样式静默忽略的派单/延迟/修复组合明确报错。
- 共享行程的 `cells` 与 `cursor` 不可被重新赋值，快照推进不会改动原环境。
- 预约视图在原路线已经结束后仍预约当前时刻的静止尾点，不凭空加入无限未来预约；更换路径或 hold 后 timeline 缓存失效。
- 旧发布器 initialize/publish/close 导入继续有效，状态仍由独立 Publisher 持有。
- 远端 main 的“完成后 advance 不再填充轨迹”和“新定位不回写已完成返程历史”保留在新内核/网关中；验解器沿用 main 独立实现。

## 验证与复现

金标准从独立 `git archive 81dc593` 源码录制，覆盖全部 23 个算法名、各合法 profile、种子 10—19，另含 V9.1 四车十二单工况，共 580 次。仅剔除真实 CPU/wall 秒数字段；路径、指派、状态标签、指标、F、路由计数、算法元数据和诊断均需完全一致。不能用新结构重新生成预期结果来“修复”差异。

```bash
.venv/bin/python tests/golden/record.py replay --report tests/golden/full-replay.json
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/ruff check src tests scripts/check_architecture.py
.venv/bin/ruff format --check src tests scripts/check_architecture.py
node --check src/agv/web/static/app.js
node scripts/check_viewer_contracts.mjs
```

默认 unittest 回放种子 10 的 58 个代表组合；完整 CLI 回放为全部 580 次，并核对回放前后的全部源码/资源 SHA-256。完整回放与性能证据保存在 `tests/golden/full-replay.json`，各项工程验证保存在 `results/architecture-refactor/verification.json`。

性能计时比较同场景旧/新执行 CPU 秒数中位数，不包括工具额外一次独立 validate；执行内部原有打分/审计仍计入。它反映本机这些场景的实现开销，不代表所有车数/订单数或部署硬件都有相同倍率，更不能表述为 F 改善。


已完成的工程验证：

| 检查 | 实际结果 |
|---|---|
| 最终 unittest（含58个代表golden回放） | 299 项全部通过，83.030 秒 |
| 独立几何/执行矩阵 | 96 组几何、24 组执行全部通过，含10车与8层 |
| 依赖与状态所有权门禁 | 零违规，CI硬检查 |
| 源码、测试和本轮脚本 Ruff | check / format 全部通过；原有已跟踪脚本另行检查通过 |
| 网页 JS 与前端合同 | 语法检查及8项前端合同通过 |
| wheel 独立安装 | 从源码目录外运行6组CLI场景与网页服务构造，通过 |
| 安装包资源一致性 | 全部94个源码/模型/网页资源与源码树逐字节一致 |
| 环境锁定与差异检查 | uv lock --check --offline、git diff --check 通过 |

wheel 场景覆盖 legacy 的学习排序入口、V4预算修复/BCRD、V9有限待命以及V9.1定位延迟/BCRD尾部保护。网页模板可生成含内嵌JS/CSS的HTML。上述是本机验证；跨平台CI结果单独以GitHub checks为准。

原来未跟踪的研究文稿、技术分析输出和临时脚本保持原样，没有纳入本次提交。其中特定旧临时脚本的格式问题不作为新代码验证通过的依据。


### 完整金标准与运行开销

最终 **580/580 次全部完成并通过独立验解**，完整规范化结果零差异。回放前后94个源码/资源文件完全一致，聚合 SHA-256 为 `0dd78533a19754235fb1cc920195e0ba6dee8396d898238f97b903fa40b05aff`。

| 场景组 | 旧版/新版 CPU 中位数倍率 |
|---|---:|
| legacy，四单两车 | 1.113× |
| V4，四单两车 | 1.739× |
| V9，四单两车 | 3.656× |
| V9.1，四单两车 | 8.889× |
| V9.1，十二单四车 | 3.267×（1.567889秒→0.479850秒） |

V9.1 两组均达到方案在本机开发场景中“至少3倍”的开销目标；不能扩展成所有地图、负载或硬件上的保证。减少重复地图复制、未来路径切片和逐对预约重建，与这些性能变化方向一致；本轮没有对每个工程机制单独做性能贡献消融。算法路径和评分保持原样。
