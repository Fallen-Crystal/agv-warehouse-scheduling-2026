# 当前可读版实现说明

2026-11-02：`code-guide/improved` 下的 14 个模块重构为规范格式与清晰命名，并作为 `current/run.py` 执行 `gate` 策略时的实际加载实现。

`runtime.zip` 保留原始冻结依赖与历史实验归档；运行入口在临时目录解压后覆盖加载上述 14 个可读版模块，同时历史实验分析仍对应原版归档。重构严格保持原有接口、校验逻辑、遗传算子、随机数调用序列和排序语义一致。

验证结果：25 项测试全部通过；40 单场景回放的完整结果与评分逐项一致；14 个模块在逆转局部重命名后的 AST 结构完全一致。

代码组织风格参考了 [DEAP algorithms.py](https://github.com/DEAP/deap/blob/master/deap/algorithms.py) 与 [NetworkX astar.py](https://github.com/networkx/networkx/blob/main/networkx/algorithms/shortest_paths/astar.py) 的模块化结构，具体算法逻辑为本项目独立实现。
