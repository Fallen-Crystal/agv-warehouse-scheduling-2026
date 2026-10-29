# WEPA源码集成与优化验证（2026-10-29）

本轮先整合通用架构分支与`origin/main@cb093a9`的推荐研究包，再迁入普通源码、验证原行为并做独立算法消融。实验执行源码快照为`ccff577`；协议`protocols/wepa-20261029-frozen.json`绑定137个包内源码／资源文件的LF规范化指纹，后续展示／接口修复不能拿新指纹重新签历史实验。

## 已落地的结构和边界

- 原ZIP329个条目、328个清单文件，SHA256=`3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b`。与原同一份SIPP、预约表共用；没有将冻结118文件的agv再拷入主线。
- 策略位于policy/wepa，数据、规则、独立验解、目标与runner各归入本职目录；CLI直接运行安装后的源码，旧current/run.py是薄包装。删除11个code-guide副本，但保留原ZIP和历史MANIFEST身份。
- 共用`world/transit.advance_fleet`作为唯一逐车移动／状态标签／实际位置／时间推进实现。WEPA快照继承相同物理实现，并有仅预测用的安静事件快进。
- 只读白名单观察屏蔽未发布任务、真实关闭时刻和最终任务总量；命令通过内核核验，诊断写回也有显式通道。
- 动态库存、入出库货位绑定、层序、锁与通用TaskBook/CommandGate仍是两个业务适配器；**M4尚未完成整个业务内核合一**。不能声称gate已可随意叠加历史定位／联合修复。
- 线性目标和历史相对目标分开；新封套含配置敏感objective_id。冻结协议和缓存键包含源码、案例、策略、种子、目标；缓存命中仍验解，不把保存CPU当新计时。
- 决策延迟支持none/fixed/measured，默认none完整金标准不变。延迟期间车辆照常执行、发布器照常发布；提交前重新规划和检查，过期不可行方案丢弃。measured依赖机器，不属于确定性金标准。

## 迁移验收

1. 旧推荐包：gate/hungarian/hga×4开发窗口×seed0×两次独立进程，24次完整轨迹与评分确定性一致，紧凑预期存于tests/golden/wepa/fixture.json。
2. 新普通源码：同24次重放全部完成，与上述逐字段指纹一致，保留完整路径、状态标签、任务分配、服务记录、搜索日志、路由计数、最终库存和F；只排除真实时钟及封套来源／输出位置。
3. 通用程序：580例金标准，0差异；全本地测试411项通过。可选CP-SAT四例的最优证书重新求解；gate/hga及三个新候选均保持最优。旧Hungarian在layers/mixed_burst的5.426%／5.833%差距被保留，未误报全部算法最优。
4. 原协议8个窗口的模型、任务、货位、初库存逐字段相等；由411830条原始请求重建窗口选择和前缀库存，与原输入审计相等。
5. 缓存冷／暖／篡改回退实测通过；即使手工更新被修改payload的完整性哈希，独立验解仍拒绝伪造D。wheel在目录外以纯标准库运行，137个源码／资源指纹与冻结协议一致。

初次完整迁移回放暴露hga在路径失败时无法写回routing_failures；该轮开发测量作废、保留本地记录，修复命令通道并重新冻结后才产生下面的正式数据。未覆盖预期轨迹或把失败悄悄删出有效轮次。

## 新协议和开发选型

原始请求固定按半开900秒完整批次取窗，筛选30–80单、SKU2–6、入出库各至少5单、前缀库存0..900且合成映射容量可行。源输入61个候选，排除7个历史窗口后剩54个；从中按日期分组和负载／入出比尽量平衡地取8开发、16验证、8封存。日期不跨集合；源和部分日期已被研究，未发现历史记录不等于全新日期，不能称完全未见留出。

所有算法参数和输入在测量前冻结并提交；种子固定0，不把随机种子当成额外独立窗口。开发阶段8窗口×4方法=32次，全部通过独立验解。选型按平均F最小、CPU打破相等；配对百分比另行作为效果描述，不与平均原始F混为同一排名指标。

| 方案 | 平均F | 窗口配对F平均改善 | 改善/退化窗口 | 平均raw CPU秒 |
|---|---:|---:|---:|---:|
| gate | 1.187567 | +0.000% | 0/0 | 36.089 |
| gate_anchor | 1.182887 | +0.424% | 3/3 | 38.827 |
| gate_tail | 1.187551 | +0.114% | 3/1 | 36.451 |
| gate_trigger | 1.187567 | +0.000% | 0/0 | 37.045 |

- gate_anchor：原6次GA候选流程、种群和随机种子保持原样，最后最多额外1次匈牙利完整SIPP预演，真实F严格改善才接受。开发平均CPU增加约7.6%，但3窗口退化，不能沿用“逐窗理论不劣”的说法。
- gate_tail：仅公开闭流后改变候选代理排序并加move_tail，仍按真实F接受。当前开发原始平均F接近持平，不能只摘取有利窗口作主线。
- gate_trigger：开放流小积压时用廉价匹配，闭流保留搜索。最初跳过闭流尾部在微型参照上退化，已按机制修复；正式开发F与gate相同，CPU没有达到下降50%目标。

选型结果在运行验证前提交为`4de270a`，选择gate_anchor；其他方法不再查询本轮验证效果。8个封存窗口未运行算法。

<!-- validation:start -->
## 验证状态

16窗口的gate和预先入选gate_anchor正在按同一冻结协议执行。尚无采用结论，默认保持原gate。
<!-- validation:end -->

## 复现与尚未实施部分

历史实验绑定源码快照：先以独立工作树检出`ccff577`，在该工作树安装，再运行冻结协议。后续仅接口／文档修复的最新HEAD可能因精确源码保护而拒绝旧协议；应检出原快照或为新实验另建协议，不要改旧报告的指纹。

```bash
git worktree add --detach /tmp/agv-wepa-repro ccff577
cd /tmp/agv-wepa-repro
python -m pip install -e .
agv experiment run --protocol protocols/wepa-20261029-frozen.json --split development --output runs/repro/development --workers 2
agv experiment select --protocol protocols/wepa-20261029-frozen.json --input runs/repro/development/runs.json --output runs/repro/selection.json
agv experiment run --protocol protocols/wepa-20261029-frozen.json --split validation --output runs/repro/validation --workers 2
agv experiment analyze --protocol protocols/wepa-20261029-frozen.json --input runs/repro/validation/runs.json --output runs/repro/analysis.json
```

未把框架迁移等同于全面业务内核合一；也未实施代理学习校正、新ALNS、gate接入历史定位、额外负载惩罚或需求先验。这些分别需要完整数据特征／接口与新协议验证，不能把文档设想当成已经得到的收益。

没有为了处理约1MB请求gzip而引入LFS或强制重写Git历史。历史ZIP仍可离线复现，后续Release外移必须先核验下载身份。网页WEPA双栏回放、严格类型检查全覆盖与更广泛敏感性研究尚未实施；当前交付是源码整合、共用物理推进、可审计实验工具和经过验证的可选机制。

所有窗口结果是公开到达记录驱动的合成仓库仿真，不是原厂实测。CPU受同机并行负载影响；默认none延迟的F不包含真实算法计算停顿。两个目标家族和不同延迟设置都不能不加标识地混比。
