# 订单邻域、路径协调与多车精确参照

本版包含本次完整算法与对照结果。默认采用 `results/summary.json` 中的推荐方案；实验候选需通过 `--profile` 明确选择，不因增加了模块就默认开启。

|参数|含义|
|---|---|
|gate|上一轮已确认的主方案：低负载即时匹配＋联合 GA＋SIPP|
|lns|将部分 GA 预算用于针对瓶颈订单的转移、交换、重插入|
|coord|分配不变，对两辆刚接单的车做局部优先级与时序重规划|
|coupled|同时启用订单邻域与局部路径协调|

四组业务规则及 F 均相同：`F=0.5*T/900+0.3*R/900+0.2*D/5400`，对应大型地图、6 车、5 层和 900 秒请求窗口。所有实际里程（含最终返库）均计入 D，T 不含最终返库耗时。其他车数应按 `LinearObjective` 的物理尺度计算，不能固定沿用 5400。

订单搜索均最多 192 次代理评估、6 次完整 SIPP 试排。路径协调有额外预算：每窗口至多 4 次，每次最多 1100 次路径调用，因此比较同时报告累计 CPU。`lns` 是针对瓶颈的有限邻域，不是完整自适应 ALNS；`coord` 是双车局部重规划，不是完整 CBS/MAPF-LNS。

实际流程：

1. 公布订单，WMS 确定合法货位，检查库存与层序。
2. 低负载即时匹配；积压时联合 GA 搜索车辆归属和订单顺序，可选瓶颈邻域。
3. 使用 SIPP 完整试排，按同一 F 选择候选，提交订单。
4. 可选路径协调：其他车辆路径固定，对两辆刚接单的车反向优先级重规划；必要时尝试 2/8 秒起步等待。候选预约安全且已知任务预测 F 严格下降才原子替换。
5. 执行一步，实际装卸完成才更新库存。下一次订单搜索读取执行后的真实位置、占用和预约。
6. 批次间安全待命，订单流真正关闭且全部任务完成后最终返库。

主算法运行只需 Python 标准库：

```powershell
python run_main.py --case wepa-day61-bin5901 --seed 0 --output trial.json
python run_main.py --case wepa-day61-bin5901 --profile lns --output orders.json
python run_main.py --case wepa-day61-bin5901 --profile coord --output paths.json
python run_main.py --case wepa-day61-bin5901 --profile coupled --output combined.json
python analyze.py
```

输出文件不能已存在。每次运行输出完整路径、任务记录、派单与协调日志、T/R/D/F 分项、CPU/wall、独立验解与代码哈希。修改代码或协议后，冻结入口会拒绝继续冒充已验证版本。

小规模精确参照需要额外安装 OR-Tools：

```powershell
python -m pip install -r requirements-exact.txt
python -m unittest test_coupled test_boundary test_variants -v
python run_exact.py --phase my-exact-check --seconds 120
```

精确参照为 2 车、2–3 单的四个预设微型问题，另附两个 4 单补充压力例。它们缩减几何尺寸，保持四邻接、三层货架服务、层序、锁、端口、库存、车辆冲突和最终返库约束。CP-SAT 联合搜索任务与轨迹，后续返库使用完整两车状态图最短路。仅 `OPTIMAL` 且上下界一致才报告最优；`FEASIBLE` 只表示找到可行解。不能据此声称动态 6 车主问题全局最优，也不能混比两类问题的 F 绝对值。

`docs/实验设计.md` 记录事前对照；`docs/结果报告.md` 记录采用结论及全部退化；`results/comparison.csv` 给出逐次数据；`results/exact-final/` 与 `results/exact-extra/` 保留整数模型、上下界、轨迹及校验结果。`baseline/` 原样保留旧版依赖，不替换仓库规则或验解器。

源请求来自固定 WEPA/slapstack 公开数据，主实验为真实请求驱动的仓库映射仿真，不是原厂实测轨迹复现。初始库存由源请求前缀台账推算。原数据与代码来源、贡献者和许可保留在 NOTICE 与冻结依赖中。
