# 仓库 AGV：简化诊断与搜索改善版

建议先阅读 [诊断与改进报告.md](诊断与改进报告.md)。本阶段在保持原仓库地图、库存/层序规则与固定线性目标不变的前提下，通过分步消融定位前期简化版本中的性能损失来源，并在新验证窗口上验证选定主方案 **`gate`**。

## 选定主线（`gate`）

1. **订单流开放且低负载**：当可见待处理订单数不超过当前空闲车辆数时，按当前预计服务耗时执行精确最小成本批量匹配（位掩码 DP），并经 SIPP 校验后即时提交，避免空车为少量已知订单等待忙车。
2. **任务积压或流关闭**：采用软分区联合 GA 同时搜索订单优先顺序与车辆归属（保留跨区接单能力），预算为至多 192 次代理评估、6 次完整可见任务试排、最多 16 代，结构简洁清晰。
3. **真实路径与滚动执行**：由原 SIPP + 预约表解决多车时空防碰撞并提交当前动作，随新订单到达滚动重规划；批次间按安全待命规则停靠，订单流关闭且全部任务完成后最终返库。

主目标固定为 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`（大型 62×47 地图、6 车、1 格/秒），`T/R` 以秒计，`D` 以格计，独立于基准算法。选定方案由 `results/selection.json` 在验证前冻结；轻负载分支对当前估计指派子问题精确求解，另配套 6 个缩减单车静态子问题的动态规划精确参照用于实现回归核验。

## 可运行入口（Python 3.12 标准库）

在解压后的研究包根目录执行（输出文件须为新路径）：

```text
python run_main.py --case wepa-day75-bin7248 --seed 0 --output my-run.json
python run_trial.py --case wepa-day75-bin7248 --profile simple --seed 0 --output simple-run.json
python -m unittest test_variants -v
```

`run_main.py` 固定执行开发集选定的 `gate` 主方案，`run_trial.py` 支持运行全部诊断对照变体。

## 目录与证据文件

- `baseline/`：191 个冻结基线文件（校验清单见 `data/baseline-manifest.json`）。
- `improved/`：各诊断变体与选定算法实现。
- `data/protocol.json`：场景、目标、种子、输入筛选与资源限制协议（第二阶段假设见 [第二阶段假设.md](第二阶段假设.md)）。
- `results/dev-components/`、`results/dev-guided/`：全部 24 次开发变体运行记录。
- `results/validation/`：4 个新窗口的配对验证结果（场景内先对 2 个随机种子取均值）。
- `results/exact.json` 与 `results/exact-traces/`：6 个缩减单车静态子问题的精确 DP 参照与逐车验解轨迹（详见 [精确参照范围.md](精确参照范围.md)）。
- `results/*probe*.json`：前缀重放与被动候选排序诊断记录。
- `results/comparison.csv`：全部原始物理指标与综合成本明细。
- `select_windows.py`：仅依据原始订单输入特征复现新窗口筛选。

请求流源自公开 WEPAStacks 数据集，地图、初始库存台账与作业速度采用课程仿真模型参数。
