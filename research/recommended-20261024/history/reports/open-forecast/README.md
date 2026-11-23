# AGV 动态预测边界对照版

本阶段基于搜索诊断轮选定的 `gate` 主方案，新增对照配置 `open_gate`，仅改变在线搜索内部对已知任务预测的终止边界条件，用于检验开放流预测终点对完整动态调度的影响。

- **`gate`**：每次内部预演将当前已知订单视为封闭批次并计入全车最终返库。
- **`open_gate`**：脱敏观察保留真实公开的“订单流是否关闭”标志；在流尚未关闭时，内部预演推进至已知任务全部完成且车辆到达安全待命固定点，待订单流真正关闭后再预演最终返库，代理排序与剪枝下界同步适配。

两种策略均使用低负载即时匹配、联合遗传搜索与 SIPP，实际物理执行、库存、层序、地图、待命与最终返库规则均保持不变。完整场景主目标固定为 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`（大型 62×47 地图、6 车、1 格/秒、900 秒请求窗口），`T` 不含最终返库耗时，`D` 含全部实际移动与最终返库。

## 运行入口（Python 3.10+ 标准库）

在解压后的研究包根目录执行（输出文件须为新路径）：

```powershell
python -m unittest test_boundary test_variants -v
python run_main.py --case wepa-day47-bin4568 --seed 0 --output trial.json
python run_main.py --case wepa-day47-bin4568 --profile open_gate --output candidate.json
```

`run_main.py` 默认运行按实验结论保留的 `gate`，可通过 `--profile` 显式切换对照配置。

## 文件与数据说明

核心改动位于 `improved/forecast.py`（预测终止与剪枝）、`improved/proxy.py`（代理终点距离）与 `improved/policy.py`（一致的关闭状态传递）；`baseline/` 为冻结依赖。详细设计与结果请参阅 [实验设计.md](实验设计.md) 与 [结果报告.md](结果报告.md)，逐次数据见 `results/comparison.csv`。

订单流来自公开 WEPAStacks / SLAPStack 固定提交数据，结合课程仿真仓库与前缀台账推算初始库存运行；验证集按输入条件固定选取 4 个此前未使用的来源日窗口（每场景 2 个随机种子，以来源日为统计单位）。
