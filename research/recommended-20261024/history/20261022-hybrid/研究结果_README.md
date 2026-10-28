# AGV 调度与混合路径算法研究包（2026-10-22）

完整可运行项目在 **agv_research/**：源码在src/agv，实验入口在scripts，测试在tests，模型与报告在docs，场景和原始轨迹在results。

本轮实现并比较了7类订单调度策略、6种路径方案。按主确认平均F较好的研究候选：静态为Portfolio＋订单/车辆联合邻域，动态为Portfolio锚点＋蚁群订单搜索，路径均使用SIPP。蚁群/粒子群路径混合未显示稳定收益。

| 配置 | 主确认48场景F平均下降 | 额外16场景F平均下降 |
|---|---:|---:|
| 统一联合邻域＋SIPP | 0.6947% | 0.4562% |
| 分场景调度＋SIPP | 0.8945% | 0.3496% |

下降均相对于上一轮Portfolio＋SIPP。分场景候选主确认平均F为0.894603，参考组为0.902909；0.8945%是逐场景相对下降率的均值，并非平均F相除。主确认27个改善、21个持平，95%种子簇bootstrap区间[0.6409%,1.1832%]，CPU成本约1.95倍。

额外种子中，动态蚁群有1/8场景相对统一方案退化。该候选不是普遍占优策略。8个双车三订单小实例达到已证最优；大规模尚未证明全局最优或近似比。F保持0.5T/Tref＋0.3R/Rref＋0.2D/Dref，未换权重来制造改善。

## 文件入口

- [完整实验报告](agv_research/docs/本轮算法实验报告_20261022.md)
- [调度与路径接口说明](agv_research/docs/调度与路径算法接口说明_20261022.md)
- [论文依据和适用边界](agv_research/docs/混合算法文献依据_20261022.md)
- [可运行项目说明](agv_research/README.md)
- [方案汇总CSV](方案汇总.csv)、[逐场景确认CSV](逐场景确认结果.csv)
- [分场景研究候选配置](agv_research/results/path-study-20261022/recommendation.json)
- [统一对照配置](agv_research/results/path-study-20261022/unified-control.json)
- [源码、公式与数据核验](agv_research/results/path-study-20261022/交付核验.json)

## 运行示例

Python 3.10及以上，在解压目录中：

```powershell
cd agv_research
$env:PYTHONPATH="$PWD/src"
python scripts/run_path_research.py --selection results/path-study-20261022/recommendation.json --regime static --output runs/static-demo.json
python scripts/run_path_research.py --selection results/path-study-20261022/recommendation.json --regime dynamic --output runs/dynamic-demo.json
```

统一方案将selection文件改为unified-control.json。可加--input读取已有场景。输出应使用新文件名。

## 核验与范围

373项本地测试、205份Python文件格式/静态检查、架构边界、8项网页契约、独立wheel安装运行通过。原评价器、验解器与仓库规则未修改；12份接口整理前后轨迹一致；518条统计记录复算F一致。

包内保留开发、确认、额外种子、消融、同订单到达对照、最优证书、压力测试、负例和各阶段源码快照。不同算法/种子对同一场景的重复执行不算独立场景。原型联调失败与因计算成本中止的记录单列，不进入性能均值。

部分版本/缓存回归测试需要本地Git快照；直接仿真无需Git。此包为本地研究交付，不表示GitHub主分支已更新。
