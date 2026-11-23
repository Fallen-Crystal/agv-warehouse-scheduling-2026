# 当前推荐方案：联合 GA + SIPP（`gate`）

本目录提供当前推荐方案的固定运行入口，仅依赖 Python 3.12 标准库即可运行，无需商业求解器或深度学习训练环境。

```bash
python current/run.py --case wepa-day45-bin4335 --seed 0 --output my-result.json
```

可在材料根目录运行，或从任意目录使用 `run.py` 的绝对路径执行（输出路径须为新文件，默认拒绝覆盖已有文件）。首次运行会校验并解压 `runtime.zip` 到 `current/_runtime/`，随后加载 [code-guide/improved](code-guide/improved) 中的可读版主线模块执行调度，并输出完整轨迹、任务记录、搜索日志、`T/R/D/F` 指标及独立验解结果。

`runtime.zip` 为可移植交付归档（相比原包仅将根目录工具脚本 `select.py` 重命名为 `select_method.py` 以避免遮蔽 Python 标准库 `select`，其余代码、协议与结果保持不变；原完整归档另存于 `history/archives/AGV_Hungarian_GA_SIPP_20261024.zip`）。包内包含 191 个冻结基线文件、开发与验证原始结果、微型最优参照、30 项单元测试、协议及文档：

- `improved/policy.py`、`improved/genetic.py`、`improved/forecast.py`：订单调度与候选预演核心；
- `baseline/engine/wepa/kernel.py`：物理执行内核；
- `baseline/engine/src/agv/planning/sipp.py`：SIPP 底层无碰撞路径规划；
- `baseline/objective.py`：独立线性目标评价函数。

首次运行或手动解压后，可在 `current/_runtime` 执行回归测试与结果核验：

```bash
cd current/_runtime
python -m unittest test_hungarian test_boundary test_variants -v
python analyze.py
python verify_input.py --raw ../../data/raw
```

执行原始数据核对前，请先在材料根目录运行 `python data/unpack.py`。其中 22 项标准库测试可直接运行；完整 30 项测试额外包含微型两车 CP-SAT 参照校验，需先安装可选依赖 `pip install -r requirements-exact.txt`，再执行 `python -m unittest test_hungarian test_coupled test_boundary test_variants -v`（OR-Tools 仅用于微型最优参照及对应测试，六车主算法运行时无需安装）。

如需开展新一轮批量对照，可使用包内 `batch.py` 与 `select_method.py`，并新建独立协议与结果目录以保持既有实验证据完整。
