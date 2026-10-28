# 单一遗传调度与三种路径后端对照

本目录是一套独立、可运行的实验代码。主线是：**邻近规则初始化 → 单一遗传算法联合搜索订单顺序与车辆 → 路径试排反馈 → 提交当前动作**。遇到新订单或规定的状态变化后重新决策。

没有在 GA 前另求一次最优匹配，也没有在 GA 后再串接独立邻域修复。它们原本分别用于优化“订单给谁”和对已有方案做局部换车/换序；取消后是否划算，由 F 与求解耗时共同检验。旧算法保留为对照，没有覆盖旧交付包。

## 先看哪些文件

- [实验报告](docs/实验报告.md)：开发、路径对照和新日期验证的结果、逐日差异、失败与局限。
- [实验计划](docs/experiment-plan.md)：运行前确定的预算、选型方式、验证窗口。
- [数据来源](data/DATA_SOURCE.md)：原始订单与仓库空间映射的区别。
- `results/comparison.csv`：逐次正式实验；`results/summary.json`：汇总。
- `results/*/traces`：完整轨迹、库存、决策与搜索预算日志。

## 调度与路径各自做什么

|部分|实现|作用|
|---|---|---|
|初始化|按预计完成时间的邻近规则|提供完整的可行参考方案|
|唯一订单搜索器|GA：排列＋车辆归属编码|同时改变派单优先顺序和分配车辆|
|可选区域引导|设备区上下两区，局部与近邻车辆优先提议|减少无效搜索；仍保留全局车辆候选，不禁止跨区|
|路径对照一|SIPP＋预约表|搜索安全时间区间并协调已提交车辆路径|
|路径对照二|时空 A*＋预约表|逐位置、逐时刻搜索，包含等待动作|
|路径对照三|蚁群引导空间 A*＋SIPP|拥堵时生成候选通道，再安排安全通过时间；不是纯蚁群|

选择哪个路径后端，预测和真实执行就使用哪个。三者均遵守四邻接、禁碰撞、装卸占位、货架层序等原规则；没有通过放松模型提高成绩。闭环路径对照的派单会受到路径反馈影响，并非固定订单分配后的纯路由对照。

GA 每次最多 96 次不同代理评价、3 次完整可见任务试排；每次试排最多 512 次底层查询。种群 12、8 代。代理评价不是实际轨迹验解，最终候选必须通过物理试排。

## 模型与评价

大型图 62×47、6 辆同构车、5 层。真实 WEPA 请求保留入/出库类别、释放时刻、SKU、批次等信息；货位、港口与服务时间映射到本项目模型。来源未提供本项目 AGV 的真实轨迹或货架布局。

入库实际完成上架才增加库存；出库完成取货才扣库存。不同批次之间待命，订单流关闭且任务全完成后最终返库。

`F = 0.5 T/T_ref + 0.3 R/R_ref + 0.2 D/D_ref`，越低越好。T 为最后任务完成时刻，R 为释放到完成的平均订单耗时，D 为包括最终返库的总里程。**所有方法统一使用同场景 FCFS＋SIPP 的分母**。

开发日期 12/32/33/45 用于选择；验证日期 62/66/69 在选择前按输入条件冻结，各高级配置运行两个种子。先平均每个日期的种子，再平均日期。没有根据验证结果重新选型，不声称全局最优。

## 运行

仅需 Python 3.10+ 标准库。路径参数按自己的解压位置替换；输出不得覆盖已有轨迹。

```powershell
python run_main.py --case wepa-day62-bin6004 --seed 0 --output my-run.json
```

`run_main.py` 自动读取**开发阶段**选出的单一调度与路径组合。若新方案在验证中不如旧版，应按报告保留旧版，不把这个入口当作无条件升级。

研究对照可显式指定：

```powershell
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router sipp --seed 0 --output soft-sipp.json
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router astar --seed 0 --output soft-astar.json
python run_simple.py --case wepa-day62-bin6004 --method soft_ga --router aco --seed 0 --output soft-aco.json
python run_simple.py --case wepa-day62-bin6004 --method adaptive_ga --router sipp --seed 0 --output old-control.json
```

`simple_ga` 是不带区域引导的简化 GA；`soft_ga` 带软区域引导；`adaptive_ga` 是未修改的旧版对照。旧版预测只适配 SIPP，所以不能与其他路径后端混搭。

单次 CLI 输出保留 T/R/D 和完整验解结果，正式 F 由配对实验共同参考统一计算。每次运行有 180 CPU 秒保护；整组驱动另有 600 墙钟秒保护。

重新核验已交付结果：

```powershell
python audit.py
python report.py
$env:PYTHONPATH='src;.'
python -m unittest discover -s tests -q
```

重新执行整组实验时，请复制到新目录并保留原始 `results`。`study.py` 拒绝覆盖已有阶段文件夹；依次运行 `dispatch`、`routing`、`validation`，会检查冻结的算法源码与协议哈希。

## 代码对应关系

- `simple/genetic.py`：唯一 GA 搜索器。
- `simple/policy.py`：事件触发、有限试排、采纳与回退。
- `simple/shadow.py`：只读已发布订单的分离预测，保持所选路径后端。
- `simple/routing.py`：路径后端工厂。
- `simple/runner.py`：完整执行与指标。
- `wepa/`：沿用的混合库存模型、执行与独立验解。
- `adaptive/`：旧版控制组。
- `src/agv/planning/hybrid_routes.py`：复用已上传版本中的 ACO 路径混合实现。

完整试排是对当前已知任务的预测，不是对未来真实订单的保证。便宜代理仍继承初始试排的货位与货架前驱近似，这也是后续可能改进的地方。
