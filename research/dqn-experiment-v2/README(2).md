# 匈牙利/自适应GA双动作DQN实验包 v2

这是此前“DQN自主选择局部F代理匈牙利或联合双概率自适应GA”的完整研究包，
不是后续搜索空间诊断包。正式F仍为 `0.5*T/900 + 0.3*R/900 + 0.2*D/5400`，
越低越好；D包括最终回库，T不包括最终回库到达时刻。

## 包含内容

- `baseline/`：191个冻结物理/规划基线文件；由 `data/baseline-manifest.json` 校验。
- `improved/`、`exact/`、`baseline/v2/`、根目录Python源码：算法选择、DQN、联合GA、匈牙利和实验运行入口。
- `data/`：协议、原始输入选择记录、动作定义及完整案例协议。
- `deliverables/wepa_real_data/`：原始订单/库存及元数据，用于复查数据来源。
- `results/adaptive_hungarian_learning_v2/`：六轮训练检查点、训练记录、验证控制、最终五日期四策略测试、审计和模型权重。
- `results/hungarian_learning_v1/`：被新版本复用并标记哈希的旧精准匹配/匈牙利对照。
- `docs/匈牙利*.md`：训练计划、结果、推断用法与限制说明。

后续搜索诊断的 `results/search_headroom_v1/`、资源链/事件代理/开放边界消融结果没有混入本包，
避免把后续未成功变体与原DQN选择实验混在一起。当前源码快照中的新增诊断脚本若在根目录，
仅作为源码快照保留；原实验的精确冻结身份以旧实验 `manifest.json` 的 hashes 为准。

## 最重要的复现入口

在包根目录、Python 3.12 + NumPy 2.3环境下：

```powershell
python -B -m unittest test_adaptive_genetic test_adaptive_visibility test_adaptive_prediction_input test_adaptive_training_diagnostics test_adaptive_learning_numerics test_adaptive_post_fit test_adaptive_learning_report
python -B predict_adaptive_hungarian_dqn.py --case-json data/hungarian_prediction_example.json --output results/new_prediction.json
```

推断入口会拒绝覆盖已有文件，并检查最佳权重、最新权重、选模、完整训练标记、源码哈希和基线哈希。
示例案例只是入口烟雾测试，不是性能证据。

## 历史结果摘要

- 最佳检查点：`results/adaptive_hungarian_learning_v2/best.npz`
- 最佳检查点SHA256（历史报告）：`b09b93be34851e24ee199ac4b147573e381985d3923d641e4f38919528788bfa`
- 五个测试日期对纯自适应GA的平均配对改善：`-0.370492%`
- 对原精准匹配：`+0.956560%`
- 对纯匈牙利：`+1.116757%`
- 这些结果是五个日期、单seed的研究证据，不是任意未知输入保证，也不宣称统计显著。

## 完整性

`PACKAGE_MANIFEST.json`列出包内每个文件的SHA256；`SOURCE_EXPERIMENT_MANIFEST.json`
复制了旧实验的原始manifest。若文件哈希不一致，请先停止复现，不要删除哈希检查或使用Python `-O`绕过保护。

生成时间（UTC）：2026-11-10T13:31:24.082957+00:00
