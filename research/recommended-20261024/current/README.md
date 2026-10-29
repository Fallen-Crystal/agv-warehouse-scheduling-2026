# 当前推荐方案：源码中的 gate＋SIPP

先在仓库根目录运行 `python -m pip install -e .`，随后可在任意工作目录使用：

```bash
agv run --profile wepa --case wepa-day45-bin4335 --algorithm gate --output my-result.json
```

原来的 `python current/run.py --case ... --seed 0 --output ...` 保留为薄兼容入口，调用已安装源码，不再隐式解压ZIP。可评审的策略位于 `src/agv/policy/wepa/`，物理状态位于 `src/agv/world/`，数据与独立验解分别位于 `src/agv/data/wepa/` 和 `src/agv/evaluation/wepa.py`。

`runtime.zip`与原MANIFEST仍保留2026-10-24的历史实验身份，未按新代码重签。旧code-guide副本已经移除；历史字节仍由原ZIP保存。新代码使用自己的源码指纹和冻结协议，细节见仓库主README及集成报告。
