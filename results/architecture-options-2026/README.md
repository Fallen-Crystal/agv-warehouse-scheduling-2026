# 本轮架构扩展：结果与复现

这些文件来自同一最终 99 文件源码/资源哈希快照（包括独立验解脚本），而不是只记录一个修改前的 Git HEAD。运行时 HEAD 为 `82ec928`，本轮修改尚未提交；重现代码以各报告的 `source_hashes` 为准。原始队友目录、全量磁盘缓存与中断运行没有上传。

## 纯性能与工程证据

| 证据 | 范围 | 结果与限制 |
|---|---|---|
| [batch-cache-final.json](batch-cache-final.json) | 2 地图 × 3 工况 × 2 种子 × 4 算法，48 冷/48 热 | 48/48 命中；50.012→13.973 秒，3.579×；热/冷 27.94%，没有达到 ≤5% |
| 同文件：cold_warm / serial_parallel / audits | 24 条代表轨迹；另 4 串行/4 并行与 2 条轨迹 | 执行/评分字段一致（排除真实计时及缓存/计时来源元数据）、轨迹字节一致；四组 verify_v91 均通过 |
| [planning-cache-final.json](planning-cache-final.json) | medium、4车12单、seed10、三工况，每后端3次，合计54次 | 静态热共享 1.131–1.173×；全轨迹/F相同且验解通过；动态ETA命中0、调用下降0%，未达40% |
| [wheel-verification.json](wheel-verification.json) | 从源码目录外运行安装包，legacy/V4/V9/V9.1 共6组CLI | 全部完成且独立验解；98个包内源码/模型/页面资源一致；新接口和HTTP服务可构造 |

冷/热墙时包括独立验解、参照重现、源码检查和IO。缓存命中保留原CPU及原测量机器/worker信息；这些CPU不是新测量。性能脚本运行时同时有4-worker质量矩阵及unittest背景负载；因此这里只报告本机配对的描述性热缓存收益，不给首次运行、隔离硬件或跨机器保证。ETA默认关闭。

```bash
python scripts/benchmark_result_cache.py --output runs/cache-check \
  --workers 2 --evidence runs/cache-check-evidence.json
python scripts/benchmark_planning_cache.py --output runs/planning-cache-check.json
python -m unittest discover -s tests -q
python scripts/check_architecture.py
python tests/golden/record.py replay --report runs/full-golden.json
```

## 行为选项与协议

开发集只用10–19，冻结后新留出集只用30–49。历史V9.1的200–219冻结集没有改写。每个场景采用相同地图、相同订单、同种子和轮转算法顺序；独立验解后计算F与P90，不把失败行删除。

- [positioning-final-config.json](positioning-final-config.json)：四档地图、三类工况、三组策略。对照为已有 `sipp_position_delay_dispatch`；`period_only`仅把重排周期设为500；`window`再加100步需求窗口。
- [positioning-development.json](positioning-development.json)：10–19开发集，共360次，全部有效。长周期的平均F改善仅0.007%，区间跨零，CPU比约0.893；短窗未显示稳定F收益。它们是开发结果，不能替代留出验证。
- [positioning-freeze.json](positioning-freeze.json)：进入留出验证之前固定配置、Spec、全部源码及留出种子列表。
- [positioning-holdout.json](positioning-holdout.json)：留出评估作为采用决策依据；不在看到留出数据后调整参数。
- [positioning-screen-final.json](positioning-screen-final.json) / [rollout-screen-final.json](rollout-screen-final.json)：仅10–12的早期开发筛选。热点冗余、保护与压缩BCRD预算未进入新留出评估，因此不把小筛选结果当作已证实收益；配置一并保留便于复现。

这些场景是固定合成仓库模板，不是公开真实物流数据。F区间以场景配对为单位bootstrap；不能解释为未见地图泛化、全局最优或未知未来订单下的P90保证。详见 [架构扩展报告](../../docs/architecture-options.md)。

## 最终留出与验收

[positioning-holdout.json](positioning-holdout.json) 有720/720有效运行：4地图×3工况×20种子×3策略。相对已有定位延迟策略，`period_only` 的240配对F平均改善0.083%（95%区间[-0.059%,0.230%]）、CPU比0.8815、P90变差21/240、空驶平均增加13.09格；`window` F平均变差0.086%（区间[-0.309%,0.131%]）、CPU比0.8925、P90变差30/240。未证明稳定F收益，默认算法与参数不变。

[golden-final.json](golden-final.json) 为完整580回放，轨迹/绑定/模拟时刻/指标/路由计数等完整规范化结果零差异，且源码前后一致。这里的旧版计时来自早先记录，新版回放有背景负载，因此不把该文件的timing_summary当作本轮配对速度提升证据。

[verification.json](verification.json) 记录345项测试、580回放、源码指纹、验解器原样、架构/格式/lock/安装包检查；[unittest.log](unittest.log) 为实际测试尾部。早期筛选对已有机制的增量比较见 [screening-decisions.json](screening-decisions.json)，只用于开发淘汰，没有在留出后调参。
