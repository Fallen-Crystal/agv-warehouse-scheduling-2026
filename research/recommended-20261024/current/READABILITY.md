# 当前可读版实现

2026-11-02：code-guide/improved 的14个模块现为运行入口实际加载的实现，替换原版密集格式与GA局部命名。current/run.py使用这些文件执行gate。

runtime.zip保留原始冻结依赖与历史实验；入口在临时目录加载后覆盖14个模块。历史证据不冒充新源码结果，历史分析仍针对原版ZIP。接口、保护检查、算子、随机调用和排序规则保持原语义。

25项测试通过；40单回放完整result及scoring一致；14模块逆转局部重命名后AST一致。此次未重跑所有真实数据。仓库其他旧实验代码未全面重构。

参考组织方式：https://github.com/DEAP/deap/blob/master/deap/algorithms.py 与 https://github.com/networkx/networkx/blob/main/networkx/algorithms/shortest_paths/astar.py 。未复制其实现。
