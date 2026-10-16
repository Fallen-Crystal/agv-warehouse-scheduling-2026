# 待命策略独立研究：2026-10-16

这里保存36个配对设置、72次执行的原始逐次统计与配对差值，另保留最有利和最不利待命案例各一组完整输入/A/B轨迹。完整72条轨迹与36个输入已在本地独立重审计；仓库遵循CONTRIBUTING只保留精选，完整结果可重新生成到被忽略的runs目录。

- `runs.csv`：72次绝对指标，包含成功/失败、计算截断、输入SHA、空驶/载货/最终归H等。
- `paired_effects.csv`、`summary.json`：36组差值、分工况/地图/种子结果；没有删去退化例。
- `protocol.json`：运行前冻结的工况、种子、规则和源码哈希。
- `compare_idle_policies.py`：原测量脚本的冻结快照，供核对script_sha256；路径沿用原工作区。实际跨平台复现用仓库scripts目录入口，策略执行函数AST相同，仅路径与输出保存适配。
- `source-lf-sha256.json`：相同生产源码的CRLF/LF规范化哈希。

```bash
python -m pip install -e .
python scripts/compare_idle_policies.py
python scripts/audit_idle_policy_comparison.py --input runs/idle-policy-study
python scripts/audit_idle_policy_comparison.py --input results/idle-policy-20261016 --summary-only
```

运行脚本默认写runs/idle-policy-study，可用AGV_IDLE_STUDY_OUTPUT环境变量指定另一个目录。复现会生成当前平台的源码与脚本哈希；不能把新哈希冒充原测量版本。summary-only检查原始CSV和精选轨迹，不冒称已经从仓库里读取了全部72条轨迹。

结果解释及论文依据见[研究报告](../../docs/idle-policy-comparison.md)，第三策略建议见[建模扩展](../../docs/idle-positioning-options.md)。研究未改当前生产待命合同，不是BCRD与待命的组合实验。
