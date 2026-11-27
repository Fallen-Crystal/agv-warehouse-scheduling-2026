# 课程报告主方案

默认运行货位—车辆联合优化与截单后反事实推演。CP-SAT 每批先最大化可派单数，再最小化局部代价，SIPP 在状态副本中验证整批路径。截单后逐条排除基准批次的指派生成候选，在确定性仿真中推演各候选，并按完整成本保留参考轨迹。

## 运行

在仓库根目录执行，OR-Tools 需要 Python 3.10 或更新版本以及对应平台的轮包。

```bash
python -m pip install -r research/course-report/requirements.txt
python research/course-report/run.py --case day19 --seed 0 --output runs/course-day19.json
python research/course-report/run.py --case size36 --mode joint --seed 0
python research/course-report/run.py --case size36 --mode fixed --seed 0
python research/course-report/verify_results.py
```

`--mode counterfactual` 为默认值。`--branch-budget` 控制每次至多尝试的受限分支数，默认随基准批次的指派数变化，六车场景至多六个。`--output` 保存逐车轨迹和推演日志，现有路径需要显式传入 `--overwrite`。评分前会调用 WEPA 独立验解。

## 输入和实现来源

- `day5`、`day19`、`day53`、`day55`、`day76` 是报告主要窗口。`day54`、`day59`、`day83` 来自原始数据中与报告表 3 的相对日及订单构成匹配的对齐小时。加载时校验原始订单和库存文件的 SHA-256，并用窗前收发净量重建初始库存。切窗结束时由仿真触发截单。
- `size6` 至 `size36` 每隔 6 单一个批次。同一 SKU 的入库与出库交替，出库先行，三个码头循环分配，订单在 0 秒发布、1 秒截单。订单顺序根据报告说明并用正式实验的匈牙利基线记录核对。
- 联合指派与推演按报告第 6、7 章和附录 C 重建，执行与独立验解调用同一份冻结 WEPA 物理内核。CP-SAT 的等价最优分支以及轨迹结果可能随执行环境变化。报告原始归档与本入口新生成的轨迹具备各自的来源。
- 评分采用报告的固定尺度，900 秒和 5400 格是归一化分母。正式结果、灵敏度表、缺少的原始记录及其核验范围见[课程报告实验索引](../../results/course-report/README.md)。
