# 仓库AGV：独立线性适应度版本

本版将优化目标与算法对照分开。主实验固定：

`J = 0.5T + 0.3R + 0.2D/(6×1)`（等效秒）

`F_linear_v2 = J/900 = 0.5T/900 + 0.3R/900 + 0.2D/5400`。

T、R以秒计，D以网格计。分母全部来自事先公开的物理/实验参数，不来自FCFS、ETA或任何其他算法。保留原权重作为暂定偏好，不声称已经业务校准。

先读[线性适应度与实验评价方案](docs/线性适应度与实验评价方案.md)，再读`docs/迁移复核报告.md`了解实际验证结果。新F不可与旧版含FCFS分母的F直接比较，也没有固定的0.8合格线。

## 文件

- `objective.py`：唯一的评分定义；独立验解后才给最终分数。
- `v2/`：已接入同一目标的简化GA、代理排序、完整试排与剪枝。
- `data/protocol.json`：冻结的权重、尺度、场景、预算和开发复核范围。
- `engine/`：逐字节保留的原物理内核、独立验解器、地图与路由依赖；哈希见`data/engine-manifest.json`。
- `run_linear.py`：便携入口，不需要先运行任何基准算法。
- `results/linear/`：原始执行轨迹与完整日志。
- `tests/`：目标一致性、物理合法性、信息隔离与复现检查。

## 运行

Python 3.12，无额外第三方依赖。

```text
python run_linear.py --case wepa-day45-bin4335 --method soft_ga --router sipp --seed 0 --output my-run.json
python -m unittest discover -s tests -v
```

输出不得覆盖已有文件。`--method`支持`soft_ga`、`simple_ga`、`eta`、`fcfs`；`--router`支持`sipp`、`astar`、`aco`。其中ACO是原ACO引导空间A*＋SIPP组合，并非单独蚁群避碰。

`study.py --run`是12次预定开发复核的执行器；交付包已经含有其结果，直接重复会拒绝覆盖。复现实验可用单次入口写入新的文件名。

本轮未修改原交付包、未重新选默认算法、未上传GitHub。输入仍是真实订单请求驱动、地图和作业参数按课程模型设定的仿真，不是原厂执行绩效。
