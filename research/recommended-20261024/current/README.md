# 当前推荐方案：联合 GA＋SIPP（gate）

这里固定提供推荐入口，避免把历史实验配置当成默认策略。Python 3.12 标准库即可运行，不需要商业求解器或训练模型。

```bash
python current/run.py --case wepa-day45-bin4335 --seed 0 --output my-result.json
```

在本材料目录运行；也可从任意目录用 run.py 的绝对路径。输出路径必须不存在。首轮会校验并解压 runtime.zip 到 current/_runtime/；此后逐文件验证，源码被修改会拒绝沿用旧实验身份。输出包含完整轨迹、任务记录、搜索日志、T/R/D、F及独立验解结果。

runtime.zip 是上一轮交付的完整原包，未改动：含全部代码、191文件冻结依赖、开发/验证原始结果、微型最优参照、30项测试、协议和文档。解压后 improved/policy.py、improved/genetic.py、improved/forecast.py 是调度核心；baseline/engine/wepa/kernel.py 是真实执行；baseline/engine/src/agv/planning/sipp.py 是底层路径规划；baseline/objective.py 是当前目标。`code-guide/`额外展示主线源码，供GitHub直接阅读；运行时使用经验证的完整包。

首次运行或手动解压后：

```bash
cd current/_runtime
python -m unittest test_hungarian test_boundary test_variants -v
python analyze.py
python verify_input.py --raw ../../data/raw
```

上面的原始数据核对前，先在材料根目录执行 `python data/unpack.py`。22项标准库测试可直接运行；完整30项还包括历史CP-SAT模型，需要 `pip install -r requirements-exact.txt`，然后 `python -m unittest test_hungarian test_coupled test_boundary test_variants -v`。OR-Tools只用于微型参照和相关测试，不是六车算法运行依赖。

新一轮大规模重跑入口是包内 batch.py/select.py，须遵守原协议的开发冻结和验证隔离；不要覆盖本次证据。新增业务窗口应新建协议和结果目录。
