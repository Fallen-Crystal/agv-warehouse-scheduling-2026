# 命令行用法与实验复现指南

本文档汇总 `agv` CLI、主线 B 推荐入口、本地质检与三套多 seed 敏感性实验的复现命令。所有命令默认从仓库根目录执行，统一使用 `uv run`。输出文件已存在时默认拒绝覆盖，如需覆盖请显式加 `--overwrite`。

## 1. 环境初始化与本地可视化

```bash
uv sync --extra dev
uv run agv serve                      # 仅绑定 127.0.0.1，浏览器可切换 Legacy / V4 / V9 / V9.1 及内置算法
```

## 2. 主线 A（自研通用引擎 CLI）

`uv run python -m agv` 等价于 `uv run agv`：

```bash
# 1. Legacy 动态场景（SIPP + 拥堵关联修复 + 6 候选预算）
uv run agv run --input examples/scenarios/dynamic_medium_burst.json --algorithm sipp_budget --output runs/demo.json

# 2. 静态首轮批次滚动优化（static only）
uv run agv run --profile legacy --mode static --tasks 12 --vehicles 4 --algorithm sipp_batch --output runs/static-batch.json

# 3. V4 分层货架 + BCRD 有序批次影子试派
uv run agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 --algorithm bcrd_budget --output runs/v4-bcrd.json

# 4. V9.1 混合背靠背货架（流式关闭 / BCRD 尾保护）
uv run agv run --profile v9.1 --mode dynamic --tasks 12 --vehicles 4 --algorithm sipp_stream_dispatch --output runs/v91-stream.json
uv run agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 --algorithm sipp_stream_bcrd_tail --output runs/v91-bcrd.json
```

## 3. 主线 B（WEPA 真实订单流推荐方案）

```bash
uv run python research/recommended-20261024/current/run.py \
  --case wepa-day45-bin4335 --seed 0 --output runs/wepa-demo.json
```

更多模型规则、算法接口与验证细节见 [research/recommended-20261024/README.md](../research/recommended-20261024/README.md)。

## 4. 开发质检与证据独立核验

```bash
make check                                                                     # ruff lint + format + 全部测试
make coverage                                                                  # 核心模块覆盖率检查（门槛 80%）
node --check src/agv/web/static/app.js && node scripts/check_viewer_contracts.mjs
uv run python research/recommended-20261024/verification/verify.py             # 校验 WEPA 材料包指纹与 ZIP CRC
uv run python scripts/verify_sensitivity_evidence.py verify results/wepa-dev-sensitivity-20261120
```

## 5. 重跑多 Seed 敏感性实验与重建团队总结 PDF

所有新运行请写入被忽略的 `runs/` 目录，避免污染已冻结的 `results/` 证据目录：

```bash
# 主线 A 核心引擎 205 次演进与超参扫描
uv run python scripts/run_core_sensitivity.py --output runs/core-sensitivity-check --workers 6

# 主线 B WEPA 既有验证窗口 156 次回顾性复评
uv run python scripts/prepare_sensitivity_runtime.py \
  --kind recommended --main-ref ea719b598662707c67f9d93b990812d4e45e24cd \
  --output runs/validation-runtime
uv run python scripts/run_wepa_validation_sensitivity.py \
  --runtime runs/validation-runtime --output runs/wepa-val-check --workers 6

# 重建团队全链路梳理与实验总结 PDF（需本机安装 Google Chrome）
uv run python scripts/build_team_summary_pdf.py --overwrite
```
