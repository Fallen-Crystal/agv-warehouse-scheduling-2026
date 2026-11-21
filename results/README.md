# 实验结果目录索引

本目录统一存放当前有效的多 seed 敏感性实验报告、全链路梳理 PDF 以及各阶段历史实验证据。新实验运行请统一输出到仓库根目录下的 `runs/`（已 gitignore），不要直接覆盖本目录中的冻结证据。

- **团队全链路梳理与实验总结 PDF**：[AGV仓库梳理与实验总结报告.pdf](AGV仓库梳理与实验总结报告.pdf)

## 1. 现行实验（2026-11）

| 实验 ID | 日期 | 主线 | 运行数 | 状态 | 报告与图表 |
|---|---|---|---:|---|---|
| `wepa-dev-sensitivity-20261120` | 2026-11-20 | B (WEPA) | 200 | 现行 | [REPORT.md](wepa-dev-sensitivity-20261120/REPORT.md) · [附录](wepa-dev-sensitivity-20261120/appendix.md) · [原9页PDF](wepa-dev-sensitivity-20261120/AGV多seed稳定性与参数敏感性研究.pdf) |
| `wepa-val-sensitivity-20261121` | 2026-11-21 | B (WEPA) | 156 | 现行（回顾性复评） | [REPORT.md](wepa-val-sensitivity-20261121/REPORT.md) · `figures/` |
| `core-sensitivity-20261121` | 2026-11-21 | A (自研引擎) | 205 | 现行 | [REPORT.md](core-sensitivity-20261121/REPORT.md) · `figures/` |

## 2. 历史阶段证据

| 目录 | 日期 | 主线 | 状态 | 说明与对应文档 |
|---|---|---|---|---|
| `v1/` | 2026-10-15 | A | 历史 | 初版调度引擎摘要与基线数据 |
| `v2/` | 2026-10-15 | A | 历史 | SIPP 工程重构与 396 次对照（见 [docs/v2-results.md](../docs/v2-results.md)） |
| `v4/` | 2026-10-15 | A | 历史 | V4 多层单面货架评审与轨迹（见 [docs/v4-review.md](../docs/v4-review.md)） |
| `v9/` | 2026-10-16 | A | 历史 | V9 混合背靠背货架开发/留出/泛化审计（见 [docs/v9-review.md](../docs/v9-review.md)） |
| `bcrd/` | 2026-10-16 | A | 历史 | BCRD 有序批次影子试派留出与事件等价复测（见 [docs/bcrd-results.md](../docs/bcrd-results.md)） |
| `idle-policy-20261016/` | 2026-10-16 | A | 历史 | 36 组待命策略配对研究（见 [idle-policy-20261016/README.md](idle-policy-20261016/README.md)） |
| `v91/` | 2026-10-17 | A | 历史 | V9.1 0.6.0 1,284 次开发与留出归档（见 [v91/README.md](v91/README.md)） |
| `framework-audit-20261017/` | 2026-10-17 | A | 历史 | 96 组可达性与 156 条历史轨迹正确性审查（见 [framework-audit-20261017/README.md](framework-audit-20261017/README.md)） |
| `training/` | 2026-10-15 | A | 历史 | 8 特征岭回归候选排序器训练记录 |
| `validation/` | 2026-10-15 | A | 历史 | 路由微基准、前端截图与公开证据核对记录 |

## 3. 历史汇总 CSV（`summary_tables/`）

`summary_tables/` 以 UTF-8 统一保留了 2026-10 至 2026-11 的 22 份正式与历史对照表，字段映射见 [00_编号索引.csv](summary_tables/00_编号索引.csv)：

- `01_正式实验/`：
  - `01_七方案汇总.csv`：WEPA 七方案汇总指标
  - `02_逐案例汇总.csv`：WEPA 逐窗口案例成绩
  - `03_逐次实验结果.csv`：WEPA 逐次执行明细
  - `04_反事实规划记录.csv`：反事实重规划对照记录
- `02_历史实验/`：
  - `01_DQN及线性基线.csv`：历史 DQN（30/60 分钟窗）及线性基线对照
  - `02_AGV历史对照/`：16 份早期探索表（`01_组合搜索.csv`、`01_综合目标.csv`、`02_混合路径方案汇总.csv`、`02_混合路径逐场景结果.csv`、`03_简化调度与路径.csv`、`04_线性目标.csv`、`05_搜索诊断.csv`、`06_开放流预测.csv`、`07_双车协调.csv`、`08_复合邻域.csv`、`09_匈牙利初始化.csv`、`10_候选探测.csv`、`10_单车方法对照.csv`、`10_单车精确参照.csv`、`10_多车松弛下界.csv`、`10_离线解码.csv`）
