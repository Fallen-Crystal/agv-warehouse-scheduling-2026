# Warehouse AGV Scheduling

仓库多车在线取送货调度实验：可安装的 Python 包、独立仿真与验解、SIPP 安全区间规划、拥堵关联路线修复，以及公开数据训练的可解释候选排序器。运行核心只依赖 Python 标准库，支持 Python 3.10+。

本项目对应人工智能基础大作业任务1。队友原来的环境与规则已按职责拆分进源码；旧的大交付目录、重复批次和历史页面已从当前版本移除。完整旧版仍可在 Git 历史提交 `d79aa07` 查阅，本机原始 Desktop 文件夹保持原样。

## 安装与运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
agv serve
```

浏览器中可选择原版、原联合重规划、SIPP、拥堵关联修复、小预算规则排序或训练后的排序。命令行可直接运行保存场景：

```bash
agv run --input examples/scenarios/dynamic_medium_burst.json \
  --algorithm sipp_budget --output runs/demo.json
```

`python -m agv` 等价于 `agv`。输出默认拒绝覆盖；需要覆盖单次结果时显式加 `--overwrite`。本地网页只绑定 `127.0.0.1`，Ctrl+C关闭服务。

## 结构

```text
src/agv/
  domain.py             场景、任务与输入约束
  simulation.py         唯一真实执行状态与原子路线提交
  planning/             A*参照、SIPP、预约索引、取送路线、联合修复
  dispatch/             派单、在线驱动、统一算法配置
  learning/             透明线性排序器与训练流程
  models/               带schema的已训练模型
  evaluation/           指标、独立轨迹/服务验解与失败诊断
  io/                   场景格式、原子文件写入、公开地图导入
  experiments/          配对实验、低层规划器独立实验
  web/                  HTTP接口、HTML模板、JS和CSS
  cli.py                统一命令行入口

tests/                  unit与integration测试
examples/scenarios/     少量可直接复现的场景
data/                  公开地图、哈希与独立许可声明
docs/                  架构、论文依据、模型卡、实测与复现
results/               精简统计、验证证据、精选轨迹
runs/                  本机生成的全量输出，不提交
```

详见 [架构与接口边界](docs/architecture.md)。工程参考实际检查了 [w9-pathfinding](https://github.com/andreyd41/w9-pathfinding)、[作者MAPF-LNS](https://github.com/Jiaoyang-Li/MAPF-LNS)、[作者RHCR](https://github.com/Jiaoyang-Li/RHCR) 和 [libMultiRobotPlanning](https://github.com/whoenig/libMultiRobotPlanning)，固定源码版本与具体借鉴见 [研究记录](docs/research/engineering-and-sipp.md)。

## 算法改进

- **SIPP状态压缩**：以“位置＋安全时间区间”代替“位置＋每一时刻”，隐式跳过连续安全等待。仍显式检查逆向边冲突、连续装卸和时限，输出逐步轨迹。原时空A*保留作差分参照。
- **复用预约索引**：同一预约版本下评估多个停靠侧和路线段时，不重复扫描整张预约表；任何集合修改都会使索引失效。
- **拥堵关联修复**：按剩余耗时与无预约下界的差、共享路段选择车辆对，而不是按相邻车辆编号；保留全车队修复候选，预留正在装卸的不可中断片段。
- **可控候选预算**：`sipp_budget`最多尝试6个候选，用较少全车队重排换取计算效率。所有候选仍需完整验解和严格改善接受。
- **可选学习排序**：`sipp_learned`在相同6候选预算下，用小型线性模型对车辆对候选排序。它只分配搜索预算，不能绕过安全规则。

[原始SIPP论文](https://publications.ri.cmu.edu/sipp-safe-interval-path-planning-for-dynamic-environments) 的思想被适配到离散单位步长和本项目服务约束；不是完整RHCR/LNS复现，也不保证全车队全局最优。A*或SIPP单段最早完成不等于全程任务调度最优。

## 公开数据与训练

包含一张 [MovingAI仓库基准地图](https://movingai.com/benchmarks/mapf.html)，原始尺寸161×63。数据采用 [ODC-By v1.0](https://opendatacommons.org/licenses/by/1-0/)，来源、哈希与改造规则见 [数据声明](data/NOTICE.md)。本项目使用不重叠区域生成在线取送货任务，属于公开几何派生的MAPD模拟数据，不能当作官方MAPF榜单成绩。

已训练8特征线性候选排序器：8个训练场景产生3,828条候选样本，3个验证场景产生1,542条样本；6个新种子和独立地图区域用于留出测试。验证MSE约比常量模型低2.52%，完整调度是否改善须看同预算留出对照，不能仅从MSE推导。没有使用私密数据集。详细作用范围、标签和局限见 [模型卡](docs/model-card.md)。

```bash
agv train --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-training
agv benchmark --seeds 10 --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-evaluation
```

## 实验与验证

最新完整对照和负面结果见 [v2实测报告](docs/v2-results.md)；逐次成绩、配置与源码哈希在 `results/v2/`。只保留精选轨迹，其他结果可用固定输入、种子及命令重新生成。v1统计在 `results/v1/`，与新实验明确区分。

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -t . -v
ruff check src tests
ruff format --check src tests
python -m build --wheel
```

已配置 Linux/macOS/Windows、Python3.10/3.12 测试，以及wheel安装后从源码目录外运行的检查。具体状态以GitHub Actions结果为准。更多复现及输出口径见 [复现指南](docs/reproduction.md)；开发约束见 [CONTRIBUTING](CONTRIBUTING.md)。

核心规则、初始贪心、时空A*及原验解器来自队友项目；新增工程结构、规划改进、训练和实验证据属于本次适配。来源与许可边界见 [NOTICE](NOTICE.md)。组员真实姓名、学号和实际贡献比例需据实填入正式课程报告。
