# V9.1 0.6.0 实验证据

结论、选型和负例见 [优化报告](../../docs/v91-optimization.md)，代码复核见 [审查记录](../../docs/v91-code-review.md)。全部为合成混合货架教学场景，正式各模板均4车、12单。F沿用同场景固定A*参照的50/30/20归一化目标，越低越好。

## 批次与文件

| 批次 | 次数 / 配对场景 | 冻结测量源码 | 逐次行与分析 | 完整证据 |
|---|---:|---|---|---|
| Stage0工具核查 | 72 / 36 | `73c56b93feb11795e0e88b03e7e6f39278b81733` | [CSV](stage0-runs.csv)、[摘要](stage0-summary.json)、[分解](stage0-effects.json)、[审计](stage0-audit.json) | [stage0.tar.gz](stage0.tar.gz) |
| 开发消融 | 252 / 同36 | `689735f5985a7c727c51b652f28c9efe128f1782` | [CSV](development-runs.csv)、[摘要](development-summary.json)、[分解](development-effects.json)、[审计](development-audit.json) | [development.tar.gz](development.tar.gz) |
| 新种子留出 | 960 / 240 | `ace242e10a16e9cb5d338bb6d1c2521b2fc136ca` | [CSV](holdout-runs.csv)、[摘要](holdout-summary.json)、[分解](holdout-effects.json)、[审计](holdout-audit.json) | [holdout.tar.gz](holdout.tar.gz) |

Stage0和Development复用了同36输入；252次不是252个独立场景。留出为200—219，与开发10—12分开。总体正式执行1284次，质量输入共276个不同场景；性能重复、微测、单元测试不计为额外独立质量样本。留出开始前已依据开发结果固定G0/G4/B0/B1四策略，没有读取留出分数后调参。

每份归档包含原始 `runs.csv`、`summary.json`、`diagnostics.jsonl`、`bounds.jsonl`、协议、源码哈希manifest及每模板首种子的完整轨迹。重复的大规模handoff文件夹、venv、缓存和其他生成目录没有上传。轨迹压缩保存，独立验解和哈希清单保持原样。

外部CSV和摘要是归档同名文件的字节副本，便于直接查看；`*-effects.json` 由提交的 `scripts/analyze_v91.py` 产生，补充单因素配对及F贡献分解。它与benchmark摘要使用不同的固定bootstrap抽样种子，因此区间末位会有轻微差别，报告采用effects文件数字。所有收益均逐配对场景计算后平均，未用平均原始T/R/D代替配对比率。

CSV的 `route_calls/expanded` 仅是真实执行环境的规划器计数，不能作为整个算法的总搜索量。额外ETA估算计数在代表轨迹的 `decision_routing_stats`，BCRD影子计数在 `dispatch_stats`（也进入逐行diagnostics）。raw CPU包含这些额外估算、影子与执行环境工作；本报告没有依据局部规划计数声称整体加速。

## 提取与重验

在完整Git克隆且已可编辑安装的环境执行，输出目录须为新的：

```bash
mkdir -p runs/v91-evidence
tar -xzf results/v91/stage0.tar.gz -C runs/v91-evidence
tar -xzf results/v91/development.tar.gz -C runs/v91-evidence
tar -xzf results/v91/holdout.tar.gz -C runs/v91-evidence
python scripts/verify_v91.py runs/v91-evidence/stage0 --revision 73c56b9
python scripts/verify_v91.py runs/v91-evidence/development --revision 689735f
python scripts/verify_v91.py runs/v91-evidence/holdout --revision ace242e
python scripts/verify_v91_release.py runs/v91-evidence/holdout --output runs/release-replay.json --workers 4
```

验核器逐项核对artifact哈希、冻结Git源码、输入场景哈希、全矩阵、F和下界差距算术及bootstrap，重新独立验解保留的代表轨迹和相应评分参照。全部正式执行在计时外已经运行独立验解；归档审计不重新运行每个未保留种子的A*分母，也不证明全局最优或任意场景完备性。不要向提取目录加入额外文件，否则artifact清单会正确拒绝它。

重跑开发/留出而不是审计归档，请使用 [固定协议](../../examples/experiments/) 与报告中的 `benchmark-v91` 命令。当前源码修复后的新输出会有自己的源码manifest，不应手动冒用历史测量提交。

## 性能和语义等价证据

发布修复源码 `32a6797` 完整重跑所有48份留出代表轨迹，严格匹配48/48；仅排除三个真实计时字段，详见 [release-replay.json](release-replay.json)。新API与网页显示修复不改变这些代表执行；不是额外48个独立场景。测试、wheel与浏览器核查见 [verification.json](verification.json) 和 [实际网页截图](ui-smoke.png)。

留出960/960完整有效。F平均改善G4 +0.640%、B0 +0.630%、B1 +0.481%；P90变差数分别为67、13、0（各240场景）。全部区间、退化数、按工况分析和CPU在effects中，不能只读均值。G4交通等待均值略增，尚未满足所有建议验收门槛。

![留出F配对收益](holdout-effects.png)

首种子200的三个精选回放：[定位与匹配正例](position-positive-replay.html)、[ETA匹配负例](matching-negative-replay.html)、[尾部保护取舍](tail-guard-replay.html)。下载HTML后本地打开，页面无需服务或外部脚本；它们只展示代表机制，选例不参与总体统计。

- [索引修订前](index-performance-before.json) 对应 `73c56b9`；[修订后](index-performance-after.json) 对应 `689735f`。每版8种场景、每种3次、索引/暴力两后端，共48次。实现之间、重复之间、版本之间完整raw哈希相同，仅剔除三个真实计时字段。
- [observe缓存微测](observe-cache-pilot.json) 是开发期探索性诊断，只改变实例的静态map生成回调，保留外层深拷贝；每图3组×30次调用，完整观察一致。该旧诊断没有独立源码manifest，约0.59—0.61的CPU比仅作局部机制描述，不列为正式速度证据。
- 完整索引计时含构建、每次hold/update及所有raw运行成本；不包含事后评分和验解。存在明显非平稳样本，不能从这组数据声称普遍加速。原始重复数值全部保留，详见审查记录的8场景表。
