# 命令行用法与实验复现手册

本文档提供 `agv` 命令行、本地 Web 界面、最终采用方案（WEPA `gate`）、自动化测试以及敏感性实验的完整复现命令。所有命令默认在仓库根目录执行，支持标准 Python 虚拟环境（`python` / `agv`）或 `uv`（在命令前加 `uv run` 即可）。输出路径若已存在，程序默认拒绝覆盖；如需覆盖请显式加 `--overwrite`。

---

## 1. 环境安装与本地 Web 可视化

```bash
# 方式 A：标准 Python 虚拟环境（Python 3.10+）
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 方式 B：uv 一键同步
uv sync --extra dev

# 启动本地可视化交互界面（自动绑定 127.0.0.1 空闲端口并打开浏览器，可用 --port 8000 指定端口）
agv serve
```

在浏览器中打开页面后，可自由切换 Legacy / V4 / V9 / V9.1 仓库布局、调整车辆数与订单数，并播放无碰撞时空轨迹。

---

## 2. 主线 B：最终采用方案（WEPA 真实订单流 `gate`）

主线 B 源码位于 `research/recommended-20261024/current/code-guide/improved/`，仅依赖 Python 3.12 标准库，无需联网或预先解压 40MB 全量订单库：

```bash
# 运行单个代表窗口（day45，默认 gate 算法）
python research/recommended-20261024/current/run.py \
  --case wepa-day45-bin4335 --seed 0 --output runs/wepa-gate-day45.json

# 运行其余验证窗口示例（day40）
python research/recommended-20261024/current/run.py \
  --case wepa-day40-bin3885 --seed 0 --output runs/wepa-gate-day40.json

# 校验推荐方案交付包的全部文件指纹与 ZIP 完整性
python research/recommended-20261024/verification/verify.py
```

如需将原始 40MB WEPA 订单库解压复核，执行：

```bash
python research/recommended-20261024/data/unpack.py
```

---

## 3. 主线 A：自研通用调度引擎（`src/agv/` CLI）

`python -m agv` 与 `agv` 完全等价：

```bash
# 1. Legacy 动态突发场景（SIPP + 拥堵修复 + 候选预算）
agv run --input examples/scenarios/dynamic_medium_burst.json \
  --algorithm sipp_budget --output runs/legacy-dynamic.json

# 2. Legacy 静态场景（首轮有序批次滚动优化）
agv run --profile legacy --mode static --tasks 12 --vehicles 4 \
  --algorithm sipp_batch --output runs/legacy-static-batch.json

# 3. V4 分层货架动态场景（推荐 bcrd_budget）
agv run --profile v4 --mode dynamic --vehicles 6 --layers 3 --tasks 18 \
  --algorithm bcrd_budget --output runs/v4-bcrd.json

# 4. V9.1 混合背靠背货架（流式关闭 / BCRD 尾保护）
agv run --profile v9.1 --mode dynamic --tasks 12 --vehicles 4 \
  --algorithm sipp_stream_dispatch --output runs/v91-dynamic.json
agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 \
  --algorithm sipp_stream_bcrd --output runs/v91-static-bcrd.json
```

---

## 4. 代码质量检查与自动化测试

```bash
# 方式 A：标准命令
python -m unittest discover -s tests -t .
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts

# 方式 B：Makefile 一键检查（含代码规范、格式与全部测试）
make check
make coverage

# 前端静态语法与契约检查（需 Node.js）
node --check src/agv/web/static/app.js && node scripts/check_viewer_contracts.mjs
```

---

## 5. 复现多 Seed 与超参数敏感性实验

新实验结果统一写入 `runs/` 目录，保持 `results/` 中既有实验数据整洁：

```bash
# 1. 核验 WEPA 开发集 200 次冻结轨迹与指标一致性
python scripts/verify_sensitivity_evidence.py verify results/wepa-dev-sensitivity-20261120

# 2. 复现主线 A 核心引擎 205 次 5-seed 演进与超参扫描（约 1 分钟）
python scripts/run_core_sensitivity.py --output runs/core-sensitivity-check --workers 6

# 3. 复现主线 B WEPA 既有验证窗口 156 次回顾性复评（约 7–8 分钟）
python scripts/prepare_sensitivity_runtime.py \
  --kind recommended \
  --main-ref ea719b598662707c67f9d93b990812d4e45e24cd \
  --output runs/validation-runtime
python scripts/run_wepa_validation_sensitivity.py \
  --runtime runs/validation-runtime \
  --output runs/wepa-val-check --workers 6
```
