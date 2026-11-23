# 待命策略独立研究（2026-10-16）

本目录保存 36 组配对场景、72 次执行的原始逐次统计与配对差值，并精选保存了最有利和最不利待命案例各一组完整输入与轨迹，其余完整轨迹可通过下方命令一键复现至 `runs/`。

- `runs.csv`：72 次绝对指标，包含完成状态、计算截断、输入哈希以及空驶、载货与最终返库里程。
- `paired_effects.csv`、`summary.json`：36 组配对差值及按工况、地图、种子维度的汇总结果。
- `protocol.json`：实验冻结工况、种子、规则和源码哈希。
- `compare_idle_policies.py`：原实验测量脚本快照；跨平台复现请使用仓库根目录的 `scripts/compare_idle_policies.py`。
- `source-lf-sha256.json`：源码 LF 规范化哈希记录。

```bash
pip install -e .
python scripts/compare_idle_policies.py
python scripts/audit_idle_policy_comparison.py --input runs/idle-policy-study
python scripts/audit_idle_policy_comparison.py --input results/idle-policy-20261016 --summary-only
```

运行脚本默认写入 `runs/idle-policy-study`（可通过 `AGV_IDLE_STUDY_OUTPUT` 环境变量自定义目录）；`--summary-only` 模式用于快速核验仓库内已保存的原始 CSV 与精选轨迹。

详细实验结论与参考文献见 [待命策略对照报告](../../docs/idle-policy-comparison.md)。
