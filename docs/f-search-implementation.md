# 本轮算法实现与证据边界

历史说明：本文对应上一轮Portfolio研究，其`results/f-study-20261022`原始数据在此前已交付的F研究包中。本次完整包的数据目录为`results/path-study-20261022`，请以[最新实验报告](本轮算法实验报告_20261022.md)为入口；本文保留作为锚点算法的来源说明。

本轮是可选研究入口，不改变公共算法注册表、网页默认策略、物理执行器和正式F。

## 实际运行的流程

1. 仅读取当前可见订单、车辆状态和已承诺轨迹。
2. 在静态距离代理中搜索订单排列。GA采用排列编码、锦标赛选择、精英保留、顺序交叉和交换变异；对照包含随机排列与GA后交换/移动局部搜索。
3. 给固定的一组当前可派订单选择车辆：可使用逐单贪心，也可使用子集动态规划求最大匹配数量下的最小总距离匹配。车辆至多10辆，因此使用位掩码状态。这是精确求解该固定小批次的指派子问题，不能称为整批F的全局最优。
4. 将代理排序靠前的三个候选交给真实SIPP影子执行，连同后续已知订单一并评估；最终候选选择仍使用T/R/D三项0.5/0.3/0.2，无单项不退化保护。
5. 真正执行仍经唯一runner和原指令入口，SIPP规划避冲突轨迹，原验解器检查完整结果。未来订单不进入观测。

R+D、T+R等选项只改变第2步的候选搜索方向。第4步以可见工作量为依据的归一化仍是代理；正式评分的完整场景固定参考只在离线评价器中使用。因此本框架不提供全局最优或近似比保证。

## 开发对照应如何解释

| 名称 | 内容 | 解释限制 |
|---|---|---|
| greedy | 原贪心+SIPP | 固定控制组 |
| v1 | 原GA订单排列+逐单选车+SIPP预演 | 新方法实际需要超越的已有版本 |
| matching | FIFO先选当前订单，再按距离作批次匹配 | 同时改变了订单选择规则，不能把它与greedy的差异全部归因于匹配算法 |
| random | 随机排列+批次匹配+校准代理 | 与GA拥有相同192次唯一代理评估上限，实际次数可能不同，日志保留 |
| ga_nomat | 新GA与校准代理，改回逐单选车 | 车匹配方式同时影响代理和执行驱动，不是独立的单函数时间测试 |
| ga_uncal | 新GA+批次匹配，未校准代理 | 校准包含到达时间、活动取货锁和开放流返程处理的整组修改，不能声称已逐项分离因果 |
| ga_T/R/D/TR/TD/RD/TRD | 对代理目标作七种预定组合 | 正式F相同；不能把代理侧重项的收益解读为修改主评价目标的证据 |
| hybrid | GA后追加交换/移动局部搜索 | 总唯一评估上限仍192，一部分预算留给局部搜索 |

每次决策的实际唯一代理次数、候选预演次数保留在轨迹的f_search.decisions字段。算法随机种子与仓库场景种子分开；正式测试使用三个算法种子，先在同场景内取均值，再进行场景配对。没有按场景挑选最好种子。

## 与课程知识和论文的对应

- 遗传算法：排列编码、交叉、变异、精英保留，能直接对应课程智能计算部分。
- 状态空间搜索：任务序列和车辆分配是上层组合空间；SIPP是基于安全时间区间的启发式图搜索，下层在已有预约条件下寻找合法路径。[SIPP原论文](https://www.cs.cmu.edu/~maxim/files/sipp_icra11.pdf)
- 局部搜索：交换和移位用于改善候选序列；还没有实现完整ALNS的自适应破坏/重建算子系统，不能把简单混合搜索包装为完整ALNS。
- 后续可借鉴LNS联合任务插入与多车优先级搜索，但不能继承其他模型下的保证。[MG-MAPD论文](https://publications.ri.cmu.edu/storage/publications/2022/08/XuIROS22.pdf)

## 执行速度核对

单个中型静态诊断场景（seed4199，4车12单）在性能剖析器下：v1 GA总约25.79秒，其中四次影子预演累计约17.77秒，约69%。GA代理搜索约0.125秒；greedy_action含几何构造/距离计算累计约3.90秒，并与预演调用嵌套，不能把这些时间简单相加。剖析本身有开销，这不是正式无干扰计时均值，也不能推广到所有规模。

因此要分别讨论求解速度与执行方案质量。更复杂的批次匹配不天然更快；调度质量也不能由函数名称或算法流行程度判断。

## 可复现入口

在项目根目录运行，先让Python能导入src目录：

```powershell
$env:PYTHONPATH = "$PWD/src"
python -B scripts/run_f_research.py --size medium --mode dynamic --tasks 8 --terms RD --optimizer-seed 0 --output runs/example-rd.json
python -B -m agv.experiments.f_benchmark --phase dev --output runs/my-development --workers 3
python -B -m agv.experiments.f_benchmark --phase final --variants greedy,v1,ga_RD,ga_TR --optimizer-seeds 0,1,2 --output runs/my-final --workers 3
```

也可安装本项目后从其他工作目录导入。所有输出选择新路径，脚本拒绝覆盖同名结果。默认仍是原正式版本，本轮配置通过显式研究脚本启用。

## 第二轮：候选组合搜索

第一轮的新场景结果未确认RD/TR单独搜索优于v1，所以增加portfolio研究选项。它保留v1的三个候选，再加入TR/RD批次匹配候选，对重复排列作去重后，最多执行九个候选的真实可见工作量预演。所有候选共享同一组评分尺度和三项权重。它同时扩展订单顺序和车辆匹配候选，但没有穷举全部指派/排序，也没有联合重排所有已承诺车辆路径。

```powershell
python -B scripts/run_f_research.py --method portfolio --size medium --mode dynamic --tasks 8 --output runs/example-portfolio.json
python -B -m agv.experiments.f_benchmark --phase dev --seed-start 5100 --variants greedy,v1,portfolio --output runs/portfolio-development --workers 3
python -B -m agv.experiments.f_benchmark --phase final --seed-start 7100 --variants greedy,v1,portfolio --optimizer-seeds 0,1,2 --output runs/portfolio-confirmation --workers 3
```

portfolio使用固定的v1+TR+RD组合与每组192次代理搜索上限；不要给它另外设置terms、budget或匹配开关来解释实验含义，这些是单一搜索模式的参数。这个冻结的研究接口不会将它们应用于portfolio。

本轮benchmark的proxy_evaluations字段对于portfolio未插桩，保留为0占位；分析时必须视为“未记录”，不可当作实际零次代理评估或用于等预算优势宣称。candidate_rollouts字段则记录实际候选预演数。其计算预算明确高于v1，性能收益与额外计算成本都必须报告。

实验分成两轮独立冻结：第一轮源文件的完整106文件快照放在results/f-study-20261022/source-phase1，以第一轮freeze.json逐字节核验；第二轮freeze.json对应portfolio代码。不是在第一轮测试过程中修改算法。先前失败的搜索方向和所有完整结果均保留。

仿真没有把算法墙钟计算时间直接加入车辆行驶时间。CPU计时是独立工程指标；当前结果不能直接声称满足实车实时调度要求。
