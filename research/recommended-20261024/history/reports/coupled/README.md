# 订单邻域、路径协调与多车精确参照

本阶段归档了订单瓶颈邻域、双车局部路径协调及微型两车 CP-SAT 精确参照的完整实现与对照实验。默认入口采用 `results/summary.json` 中选定的主方案 `gate`，其余三种实验配置通过 `--profile` 参数显式调用。

| 参数 | 策略说明 |
|---|---|
| `gate` | 上一轮确认的主方案：低负载即时匹配 + 联合 GA + SIPP |
| `lns` | 将部分 GA 预算分配给针对瓶颈订单的转移、交换与重插入邻域 |
| `coord` | 保持任务分配不变，对同一时刻刚接单的两辆车执行局部优先级与起步时序重规划 |
| `coupled` | 同时启用瓶颈订单邻域（`lns`）与双车局部路径协调（`coord`） |

## 目标口径与搜索流程

四组实验采用统一规则与线性目标 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`（大型 62×47 地图、6 车、5 层、900 秒请求窗口；若变更车队规模，`LinearObjective` 按对应物理尺度 `m*v*H` 自动计算）。`T` 不含最终返库耗时，`D` 含全部实际移动与最终返库。

四组订单搜索上限均为 192 次代理评估与 6 次完整 SIPP 试排；`coord` 与 `coupled` 额外配置了有界局部路径协调预算（每窗口至多 4 次，每次至多 1,100 次路径调用），实验同步报告累计 CPU 时间以反映综合计算开销。其中 `lns` 为面向瓶颈订单的轻量局部邻域搜索，`coord` 为固定他车预约下的双车优先级局部重规划。

调度执行流程如下：
1. 发布可见订单，由 WMS 分配合法货位并检查库存与层序。
2. 低负载时执行即时批量匹配；积压时执行联合 GA（可选启用瓶颈订单邻域）。
3. 通过 SIPP 完整试排按同一 F 择优提交订单。
4. 可选执行双车路径协调：固定其余车辆轨迹，交换两辆刚接单车辆的 SIPP 规划优先级，并在衔接冲突时尝试 2 秒或 8 秒起步等待；仅当预约安全且已知任务预测 F 严格降低时原子替换。
5. 推进物理执行并在实际装卸完成时更新库存；下一轮决策读取真实位置、占用与预约状态。
6. 批次间空车安全待命，订单流关闭且全部任务完成后统一返库。

## 运行入口与精确参照

主算法仅需 Python 标准库（在解压后的研究包根目录执行，输出路径须为新文件）：

```powershell
python run_main.py --case wepa-day61-bin5901 --seed 0 --output trial.json
python run_main.py --case wepa-day61-bin5901 --profile lns --output orders.json
python run_main.py --case wepa-day61-bin5901 --profile coord --output paths.json
python run_main.py --case wepa-day61-bin5901 --profile coupled --output combined.json
python analyze.py
```

微型两车精确参照需额外安装可选依赖 OR-Tools：

```powershell
python -m pip install -r requirements-exact.txt
python -m unittest test_coupled test_boundary test_variants -v
python run_exact.py --phase my-exact-check --seconds 120
```

精确参照包含 4 个 2 车 2–3 单的预设微型问题及 2 个 4 单补充压力例。模型在缩减几何尺寸的同时完整保留四邻接、3 层货架服务、层序、货架锁、端口、库存、多车防碰撞与最终返库约束，由 CP-SAT 联合优化任务与轨迹，并在最后任务完成后通过完整两车状态图最短路精确计算返库尾部成本。求解状态中 `OPTIMAL`（且上下界一致）表示该微型例的已证最优解，`FEASIBLE` 表示可行解。

## 文档与数据出处

详细设计与结论请参阅 [实验设计.md](实验设计.md) 与 [结果报告.md](结果报告.md)，逐次指标位于 `results/comparison.csv`，整数规划模型与证书保存在原归档的 `results/exact-final/` 与 `results/exact-extra/`。订单流源自 WEPAStacks / SLAPStack 公开数据集，结合课程仿真仓库模型与前缀台账推算初始库存运行。
