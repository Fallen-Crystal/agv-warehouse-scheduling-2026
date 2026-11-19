# 匈牙利/GA DQN冻结推断用法

该入口需要本轮训练和验证完整完成后产生的最佳模型。模型尚未生成时，脚本会停止，不会悄悄使用旧模型或改成手工阈值。

在项目根目录运行：

```powershell
python -B predict_hungarian_dqn.py --case-json data/hungarian_prediction_example.json --output results/user_prediction_example.json
```

默认使用 `results/hungarian_learning_v1/best.npz`，并核对训练实现哈希和训练完成标记。推断固定使用Q值贪心选择，动作0为F局部代理匈牙利，动作1为原joint GA。不会更新网络、Adam、经验池或随机源；物理与GA随机seed默认为0，可通过 `--seed` 指定。

## 新订单格式

输入为单个案例JSON。`data/hungarian_prediction_example.json` 是独立的两条合成订单，仅作格式和功能示例，不属于模型实验的训练或最终测试成绩。

```json
{
  "case": "my-new-orders",
  "close_at": 1800,
  "initial": {"101": 1},
  "tasks": [
    {"id": 0, "kind": "delivery", "sku": 101, "release": 0, "source_dock": 1},
    {"id": 1, "kind": "retrieval", "sku": 101, "release": 300, "source_dock": 1}
  ]
}
```

- `case`：案例名称。
- `close_at`：完整输入窗口长度，正整数秒。
- `initial`：窗口开始时各SKU的库存，数量为非负整数；键是SKU编号。
- `tasks`：按发布时间排序的完整订单，每条为一个货盘请求。
- `id`：唯一整数；`sku`：存在于initial中的整数编号。
- `kind`：`delivery`为入库，`retrieval`为出库。
- `release`：从窗口开始计的整数秒，满足0≤release<close_at；同一时刻整批订单应完整保留。
- `source_dock`：从1开始的源口编号，沿用原build规则映射到固定入/出库口。

每个SKU采用与实验相同的初始库存+50容量余量，逐笔库存前缀必须合法。实际货架位置仍由固定seed17的原映射生成，用户订单不能直接指定另一座仓库的布局。

## 输出与边界

输出JSON包含正式F、T/R/D、交通等待、逐决策动作与奖励、匈牙利/GA选择次数、模型哈希、输入哈希和冻结验证标志。动作次数表示策略调用次数；一次调用可能沿用已有GA计划或遇到暂时无法提交的任务，不能解释成等量的独立GA搜索或订单数。

`--output`必须是新的JSON路径，脚本拒绝覆盖现有结果。输入订单数、SKU数、初始库存或时长超出本轮训练筛选范围时，会输出明确警告；即使输入位于范围内，也不保证优于三个固定基线。两条示例订单会触发范围警告，属于预期行为。

最终实验测试由单独执行器完成；使用新订单推断入口试跑已封存测试会破坏未见性，因此研究期间不要将最终测试案例当作调参输入。
