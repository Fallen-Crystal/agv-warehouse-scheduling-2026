# 单一遗传调度与三种路径后端对照

本阶段研究简化调度架构与多路径后端的综合表现。调度主线精简为：**邻近规则初始化 → 单一联合遗传算法搜索订单顺序与车辆归属 → 路径后端试排反馈 → 提交当前动作**，并在新订单到达或满足重规划条件时滚动决策。

相比旧多段混合框架，本版取消了 GA 前的独立匹配求解器与 GA 后的独立邻域修复，通过统一目标 `F` 与求解耗时共同衡量结构简化的效果，旧版算法完整保留作为对照组。

## 文档索引

- [实验报告.md](实验报告.md)：开发、路径对照与新日期验证的完整指标、逐日配对与分析；
- [experiment-plan.md](experiment-plan.md)：运行前固化的预算、选型规则与验证窗口；
- `results/comparison.csv`、`results/summary.json`：逐次实验明细与汇总统计（完整轨迹保存在对应归档的 `results/*/traces`）。

## 调度与路径组件

| 组件 | 实现方式 | 作用说明 |
|---|---|---|
| 初始化 | 按预计完成时间的邻近规则 | 生成完整可行的初始参考方案 |
| 订单搜索器 | 联合 GA（排列 + 车辆归属双基因编码） | 同步优化派单优先顺序与分配车辆 |
| 软区域引导（可选） | 按设备区上下两区组织候选车池 | 优先提议同区及较早空闲车辆，同时保留 25% 全局提议支持跨区 |
| 路径后端一 | SIPP + 预约表 | 压缩安全时间区间并协调已提交车辆预约 |
| 路径后端二 | 时空 A\* + 预约表 | 逐格逐时刻搜索无碰撞路径（含等待动作） |
| 路径后端三 | 蚁群引导空间 A\* + SIPP | 拥堵时生成候选空间通道，再由 SIPP 安排安全通行时间窗 |

所选路径后端同时用于内部试排与真实物理执行，三类后端均严格遵守四邻接、防碰撞、装卸占位与货架层序规则。由于路径反馈会影响后续滚动派单，本对照属于端到端的闭环系统评估。

GA 搜索预算固定为种群 12、8 代、每次至多 96 次去重代理评价与 3 次完整可见任务试排（每次试排至多 512 次底层路由查询），所有采纳候选均通过完整物理试排校验。

## 仿真模型与评价口径

环境固定为大型 62×47 地图、6 辆同构车、5 层货架；采用 WEPAStacks 真实入/出库请求（保留任务类别、到达时刻、SKU 与批次），映射至课程仓库模型。入库上架完成增加库存，出库取货完成扣减库存；批次间安全待命，订单流关闭且任务完成后统一返库。

本阶段采用旧版相对归一化目标 `F = 0.5*T/T_ref + 0.3*R/R_ref + 0.2*D/D_ref`（越低越好），同一场景下所有方法统一以 `FCFS + SIPP` 作为公共参考分母。开发集使用第 12/32/33/45 日，验证集使用按输入条件选出的第 62/66/69 日（高级策略每窗口运行 2 个随机种子，先日内平均再跨日平均）。

## 运行方式（Python 3.10+ 标准库）

在解压后的研究包根目录执行（输出路径须为新文件）：

```powershell
python run_main.py --case wepa-day62-bin6004 --seed 0 --output my-run.json
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router sipp --seed 0 --output soft-sipp.json
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router astar --seed 0 --output soft-astar.json
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router aco --seed 0 --output soft-aco.json
python run_simple.py --case wepa-day62-bin6004 --method adaptive_ga --router sipp --seed 0 --output old-control.json
```

其中 `simple_ga` 为无区域引导简化 GA，`soft_ga` 为软区域引导简化 GA，`adaptive_ga` 为旧版控制组（仅适配 SIPP 后端）。单次运行设 180 CPU 秒与 600 墙钟秒保护；复核与测试命令如下：

```powershell
python audit.py
python report.py
$env:PYTHONPATH='src;.'
python -m unittest discover -s tests -q
```

## 核心代码映射

- `simple/genetic.py`：联合编码 GA 搜索器；
- `simple/policy.py`：事件触发、试排择优与回退控制；
- `simple/shadow.py`：只读已发布订单的后端一致滚动预测；
- `simple/routing.py`：路径后端工厂；
- `simple/runner.py`：完整执行与指标汇总；
- `wepa/`：混合库存物理内核与独立验解器；
- `adaptive/`：旧版对照调度器；
- `src/agv/planning/hybrid_routes.py`：ACO 引导空间 A\* + SIPP 混合路径实现。
