# 匈牙利与自适应GA双动作DQN：新订单推断

此入口针对双概率自适应GA版本。动作0使用正式F的局部代理匈牙利匹配，动作1使用联合顺序/车辆归属GA；交叉率和变异率随当前搜索的停滞与多样性调整。推断时网络按Q值自主选动作，不使用订单日期、固定负荷阈值或未来未发布订单。

## 使用时机与命令

先完成六轮训练和验证选模，再加载最佳模型。入口会核对冻结源码、协议动作语义、完整轮次、最佳/最新模型哈希及选模记录，状态不完整时不会生成推断结果。

在研究目录执行：

```powershell
python -B predict_adaptive_hungarian_dqn.py --case-json data/hungarian_prediction_example.json --output results/new_adaptive_prediction.json
```

输出必须使用尚不存在的JSON路径，防止覆盖历史记录。`--seed`默认0，控制物理/GA随机源，不开启探索。脚本默认加载`results/adaptive_hungarian_learning_v2/best.npz`。实验数据和源代码具有固定哈希，修改已冻结实现后应建立新版本。

提供的示例是独立合成的两条订单，仅用于验证入口，不计入任何实验性能。它小于训练窗口的订单范围，因此输出会明确提示域外输入。

## 环境与迁移复查

这是一套带完整性检查的研究入口，不是只携带一个权重文件即可运行的独立部署包。迁移时优先保留完整研究目录的相对结构，包括baseline、data、improved以及本实验结果目录；不要只复制最佳模型和推断脚本。入口除加载最佳模型外，还会核对最新模型、选模记录、完整训练标记、六轮学习曲线、冻结源码清单和基线文件。

已记录的恢复环境是Python 3.12.14、NumPy 2.3.5，详见[数值环境记录](<../results/adaptive_hungarian_learning_v2/recovery_numeric_environment.json>)。这些版本记录不代表已验证跨平台或不同BLAS后端逐位一致。换机后先检查环境版本并运行回归测试，再用独立示例检查推断；不要通过删除校验、改写哈希或添加Python的`-O`参数来绕过不一致。

```powershell
python -c "import sys,numpy; print(sys.version); print(numpy.__version__)"
python -B -m unittest test_adaptive_learning_numerics test_adaptive_prediction_input test_adaptive_visibility
```

完整六轮训练之前，示例推断也会被拒绝，这是预期保护，不应通过伪造完成标记解决。上述环境与回归检查不会替代正式四策略性能比较。

## 单个案例的JSON结构

```json
{
  "case": "new-orders-example",
  "close_at": 1800,
  "initial": {"101": 1},
  "tasks": [
    {"id": 0, "kind": "delivery", "sku": 101, "release": 0, "source_dock": 1},
    {"id": 1, "kind": "retrieval", "sku": 101, "release": 300, "source_dock": 1}
  ]
}
```

| 字段 | 含义与限制 |
|---|---|
| case | 非空案例名称 |
| close_at | 发布窗口结束秒数，正整数；订单发布时刻必须严格小于该值 |
| initial | SKU到初始库存的映射；JSON键为数字字符串，库存为非负整数 |
| tasks | 非空订单数组，按release非递减排列 |
| id | 每条订单唯一的整数编号 |
| kind | delivery表示入库，retrieval表示出库 |
| sku | 整数SKU，必须在initial中定义 |
| release | 相对窗口开始的整数秒，满足0≤release<close_at；禁止布尔值或浮点数 |
| source_dock | 正整数源码头编号，由原固定场景映射为进/出库口 |

程序验证每个SKU的库存前缀不小于0且不超过initial+50。initial中的键转换为整数后必须唯一，例如同时提供"1"和"01"会被拒绝，避免库存数量被静默覆盖；库存数量不会把布尔值或浮点数自动转成整数。物理执行还会核对货架容量、AGV动作和SIPP轨迹，输入账本通过不等于任意输入都能成功执行。

训练输入范围为每窗口40至240条完整订单、1至5个SKU、初始库存合计不超过900、窗口1800或3600秒。超出该范围会标记`outside_training_input_range=true`，不能据此承诺性能。

## 输出与冻结状态

输出包含正式F、T/R/D、动作次数、逐决策转移、GA逐代概率及触发记录、输入哈希和模型哈希。F=0.5T/900+0.3R/900+0.2D/5400，越低越好。T不计最终回家完成时刻，D包括回家距离。

`ga_adaptation`记录规则版本；`ga_searches`保存每次搜索的交叉率、顺序/归属变异率、停滞代数、联合多样性及操作次数。交叉触发或变异触发不一定形成不同基因，不能把触发次数当成不同候选数。

`frozen_state_verified=true`表示本次推断前后在线网络、目标网络、Adam、经验池、随机源及待提交多步队列逐项不变。输出中的转移用于追溯奖励和轨迹，不会用于训练。

## 如何理解成绩

一份新订单输出只代表该策略在这一输入上的正式物理评分。要比较改善率，三个基线必须使用同一订单、库存、场景、随机种子及预算。DQN自主选择动作并不保证任意未知输入都比三个基线好；最终报告会分别披露平均配对改善和逐日期胜负。
