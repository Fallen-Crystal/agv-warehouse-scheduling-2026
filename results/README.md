# 实验结果目录索引

本目录按“现行多 seed 敏感性实验”“历次版本演进阶段证据”和“历史汇总 CSV”三类组织。本地新运行的实验建议输出到仓库根目录的 `runs/`（已 gitignore），以便保持本目录结果清晰稳定。

## 1. 现行多 Seed 与超参数敏感性实验（2026-11）

| 实验 ID | 日期 | 主线 | 有效运行 | 说明 | 报告与图表 |
|---|---|---|---:|---|---|
| `wepa-dev-sensitivity-20261120` | 2026-11-20 | B (WEPA) | 200 | 开发窗口：7 方案演进 + 预算 2×2 + 自适应 2×2 | [REPORT.md](wepa-dev-sensitivity-20261120/REPORT.md) · [逐日附录](wepa-dev-sensitivity-20261120/appendix.md) · `figures/` |
| `wepa-val-sensitivity-20261121` | 2026-11-21 | B (WEPA) | 156 | 既有验证窗口回顾性复评 + 扩大预算与组合对照 | [REPORT.md](wepa-val-sensitivity-20261121/REPORT.md) · `figures/` |
| `core-sensitivity-20261121` | 2026-11-21 | A (自研引擎) | 205 | Legacy / V4 / V9.1 跨版本演进与超参扫描（5 seeds） | [REPORT.md](core-sensitivity-20261121/REPORT.md) · `figures/` |

## 2. 历次版本演进阶段证据

| 目录 | 日期 | 主线 | 说明与对应演进文档 |
|---|---|---|---|
| `v1/` | 2026-10-15 | A | 初版调度引擎基线数据（见 [docs/history/v1-report.md](../docs/history/v1-report.md)） |
| `v2/` | 2026-10-15 | A | SIPP 安全区间规划重构与 396 次对照（见 [docs/v2-results.md](../docs/v2-results.md)） |
| `v4/` | 2026-10-15 | A | V4 多层单面货架建模与代表轨迹（见 [docs/v4-review.md](../docs/v4-review.md)） |
| `v9/` | 2026-10-16 | A | V9 混合背靠背货架开发、留出与泛化结果（见 [docs/v9-review.md](../docs/v9-review.md)） |
| `bcrd/` | 2026-10-16 | A | BCRD 有序批次影子试派实验结果（见 [docs/bcrd-results.md](../docs/bcrd-results.md)） |
| `idle-policy-20261016/` | 2026-10-16 | A | 36 组待命策略配对实验（见 [docs/idle-policy-comparison.md](../docs/idle-policy-comparison.md)） |
| `v91/` | 2026-10-17 | A | V9.1 流式关闭与优化实验归档（见 [docs/v91-optimization.md](../docs/v91-optimization.md)） |
| `training/` | 2026-10-15 | A | 8 特征岭回归候选排序器训练记录 |
| `validation/` | 2026-10-15 | A | 路由微基准、前端截图与公开测试记录 |

## 3. 历史汇总 CSV（`summary_tables/`）

`summary_tables/` 以 UTF-8 编码归档了 22 份实验汇总表，字段编号映射见 [00_编号索引.csv](summary_tables/00_编号索引.csv)：

- `01_正式实验/`：`01_七方案汇总.csv`、`02_逐案例汇总.csv`、`03_逐次实验结果.csv`、`04_反事实规划记录.csv`
- `02_历史实验/`：`01_DQN及线性基线.csv`，以及 `02_AGV历史对照/` 下 16 份早期方案探索记录表
