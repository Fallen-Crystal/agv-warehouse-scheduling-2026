# 匈牙利 / 自适应 GA 双动作 DQN 实验包（v2）

本目录保存“DQN 自主选择局部 F 代理匈牙利或双概率自适应联合 GA”的实验源码、数据集摘要、最终评估结果与最佳模型权重。主评价目标为 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`（越低越好），其中 `T` 为最后一单完成时刻，`R` 为订单平均响应耗时，`D` 为含最终返库在内的总移动格数。

## 目录内容

- `improved/` 与根目录 Python 脚本：双概率自适应联合 GA、局部 F 代理匈牙利算法、Double DQN 策略网络、训练/诊断/审计及推断脚本。
- `data/`：实验窗口定义、订单数据可读表、日级统计汇总、数据校验清单及推断示例（`hungarian_prediction_example.json`）。
- `results/adaptive_hungarian_learning_v2/`：最佳检查点 `best.npz`、学习曲线、验证选模记录、五日期四策略配对结果（`paired_results.csv`）及各项汇总与审计 JSON。
- `docs/`：实验结果报告，包含 [匈牙利替换实验结果.md](docs/匈牙利替换实验结果.md) 与 [匈牙利自适应GA-DQN重训练结果.md](docs/匈牙利自适应GA-DQN重训练结果.md)。

## 推断入口示例

在具备对应冻结基线依赖的 Python 3.12 + NumPy 2.3 环境下，可通过以下脚本执行单案例推断演示（示例案例用于验证推断接口与输入校验流程）：

```bash
python -B predict_adaptive_hungarian_dqn.py \
  --case-json data/hungarian_prediction_example.json \
  --output results/new_prediction.json
```

推断脚本默认拒绝覆盖已有输出文件，并在运行前核验最佳权重、选模记录、训练完成标记与源码指纹。

## 实验结果摘要

- 最佳检查点：`results/adaptive_hungarian_learning_v2/best.npz`
- 最佳检查点 SHA256：`b09b93be34851e24ee199ac4b147573e381985d3923d641e4f38919528788bfa`
- 5 个测试日期（单 seed）相对纯自适应 GA 的平均配对改善：`-0.370492%`
- 相对原精准匹配的平均配对改善：`+0.956560%`
- 相对纯匈牙利的平均配对改善：`+1.116757%`

上述指标来自 5 个未参与训练的来源日窗口、固定单 seed 下的配对评测，反映了当前训练规模与配置下的实测效果，详细分析见 [匈牙利自适应GA-DQN重训练结果.md](docs/匈牙利自适应GA-DQN重训练结果.md)。

生成时间（UTC）：2026-11-10T13:31:24.082957+00:00

---

## 仓库去重与整理说明

- 原始 40MB WEPA 订单文件（`1_layout.csv`、`2_orders.json.gz`、`3_initial_fill_lvl.json`）已在 `research/recommended-20261024/data/raw/` 统一保存，此处不再保留重复压缩包。
- 中间过程检查点（`train_e*.npz` / `epoch*.npz`）及历史基线引擎副本已从主干移除以减少仓库体积；本目录保留最佳检查点 `results/adaptive_hungarian_learning_v2/best.npz`、核心源码、结果文档与汇总评估指标（完整原始包历史保留在 Git 提交 `ed2bd0a`）。
