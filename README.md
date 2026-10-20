# Warehouse AGV Scheduling

仓库多车在线取送货调度实验：可安装的 Python 包、独立仿真与验解、SIPP 安全区间规划、拥堵关联路线修复，以及公开数据训练的可解释候选排序器。运行核心只依赖 Python 标准库，支持 Python 3.10+。

本项目对应人工智能基础大作业任务1。队友原来的环境与规则已按职责拆分进源码；V4 新增的分层货架、专用交付点与几何规则也已接入同一套环境、SIPP 和独立验解器。旧的大交付目录、重复批次和历史页面没有重新复制进仓库。完整旧版仍可在 Git 历史提交 `d79aa07` 查阅，本机原始 Desktop 文件夹保持原样。

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

### 使用 V4 仓库规则

网页的“仓库模型”选择 V4 后，可设置1–10辆车、货架层数、作业通道宽度和建筑障碍。命令行通过显式 profile 生成 V4 场景；下面以距离贪心建立同规则基线：

```bash
agv run --profile v4 --mode dynamic --vehicles 10 --layers 3 \
  --obstacles columns_equipment --tasks 24 --algorithm baseline \
  --output runs/v4-baseline.json
agv benchmark-v4 --seeds 6 --output runs/v4-reproduction
```

也可直接使用 [V4 动态示例](examples/scenarios/v4_small_dynamic.json)：`agv run --input examples/scenarios/v4_small_dynamic.json --algorithm baseline --output runs/v4-example.json`。

CLI 默认仍为 `--profile legacy --algorithm sipp_budget`。V4 在不传 `--horizon` 时运行到完成或检测到停滞；网页使用有限步数上限，导入 `horizon: null` 的文件请用 CLI。`--input` 会完整使用文件内场景，生成参数不改写该输入。算法可显式换成 `sipp_budget` 或 `sipp_matching` 比较。

V4 的有效变化、三处修复、54次配对运行和后续方向见 [V4 集成审核](docs/v4-review.md)。这批实验中 SIPP 联合修复的综合分数有升有降，尚不足以替代 V4 距离贪心基线；业务规则更完整与调度算法更优需要分别验证。

## BCRD 有序批次派单

新增 `bcrd_budget`：只用可见订单生成有序批次，复用真实 SIPP 做影子试派和保底 rollout，在明显积压时搜索；不改变路径和仓库规则。命令示例：

```bash
agv run --profile v4 --tasks 18 --vehicles 4 --algorithm bcrd_budget --output runs/bcrd.json
```

算法边界、配对实验和成本见 [BCRD 执行报告](docs/bcrd-results.md)，诊断与安全合同分别保存在关联文档。新策略保持为可选入口；CLI和网页默认值保持原样。

90个留出场景的综合F平均改善0.406%，其中静态积压场景改善1.166%；动态设备场景区间跨零，共享站场景没有收益。事件推进与逐步影子逐字段等价，将同轮CPU/G0从3.16降到1.77。另有20个尺寸/负载泛化场景。完整运行共1400次，含开发、消融与重复种子的实现等价复测，不能当作1400个独立质量样本。响应尾部仍有退化，详见报告中的负面结果和停止条件。

可直接打开[同种子双栏离线回放](results/bcrd/replay.html)观察真实轨迹；精选案例同时展示完工改善与平均响应、里程的代价。正式 `benchmark-bcrd` 需Git检出并可编辑安装，以保存来源提交和源码哈希。

## 当前业务规则：V9.1

当前采用 **批次之间待命，所有批次完成后最终返库**。新增 `v9.1` profile，保留四档审定地图、1—10辆车、3—8层、单排双侧/背靠背独立排及50/30/20归一化目标。订单流由外部发布器明确关闭，算法不能提前看结束时间或未来订单数量；无固定等待额度。最终返库按实际轨迹验解，距离及0.05D能耗估算完整计账。

```bash
agv run --profile v9.1 --mode dynamic --tasks 12 --vehicles 4 --output runs/current.json
```

此入口默认使用 `sipp_stream_dispatch`；网页默认选择V9.1，不要求填写仿真步数上限，支持无截止场景导入与同步订单流状态。也可运行 `--algorithm baseline`。

数学模型、规则和接口见 [V9.1算法交接](docs/modeling-v9.1.md)，初次业务接入验证见 [V9.1验证](docs/v9.1-validation.md)。0.6.0新增可选的安全选点定位、SIPP完成时间匹配、有限延迟派单，以及适配真实订单流的BCRD与可见订单P90保护；机制、同场景消融、留出实验和限制见 [本轮优化报告](docs/v91-optimization.md)。默认策略保持原样，旧规则的联合重规划入口仍不能直接与当前profile组合。

```bash
agv run --profile v9.1 --mode dynamic --tasks 12 --vehicles 4 \
  --algorithm sipp_position_delay_dispatch --output runs/current-positioning.json
agv run --profile v9.1 --mode static --tasks 12 --vehicles 4 \
  --algorithm sipp_stream_bcrd_tail --output runs/current-bcrd.json
agv benchmark-v91 --protocol examples/experiments/v91-development.json \
  --output runs/v91-reproduction --workers 4
```

新机制均通过显式算法名启用。定位与BCRD分别验证，当前没有提供二者的未经验证组合。全程重定位、等待和最终返库均参与验解与计账；P90保护作用于已发布订单的预测，不能保证未知订单到来后的实际P90。实验使用合成场景，没有重新训练旧模型或使用私密数据。下文V9有限待命及BCRD数字继续属于历史实验。

## 待命与可中途接单返库的独立比较

新增四种地图×三类工况×三个种子的36组配对、72次执行，使用相同贪心与SIPP，均计最终返库。近卸货口安全待命在稀疏工况平均空驶减少17.61%、F改善2.71%；共享出口批量工况F变差0.32%。每设置仅三个种子，属于探索性结果，没有普遍最优或真实电池节能的宣称。

论文、实验定义及限制见[对照研究](docs/idle-policy-comparison.md)；分散/动态定位的设计见[待命位置建模建议](docs/idle-positioning-options.md)。第三策略的0.6.0实现与新规则实测另见 [本轮优化报告](docs/v91-optimization.md)；此处保留原比较结论与业务合同。

紧凑统计、原始逐次CSV和正/负精选轨迹见[结果与复现](results/idle-policy-20261016/README.md)。研究F使用同场景SIPP返库方案为固定参照，不与生产A*分母或历史报告F直接混比。

## 历史 V9 混合货架与有限待命

队友V6/V9的有效建模内容已通过独立 `v9` profile 接入：横竖混合背靠背货架、首排单层双侧候选、3–8层独立排、对齐净空与中央设施。原V4和历史结果保留；地图、任务和新参考分母不同，不直接横比两版F。

```bash
agv run --profile v9 --tasks 12 --vehicles 4 --algorithm sipp_greedy_dispatch --output runs/v9-return.json
agv run --profile v9 --tasks 12 --vehicles 4 --algorithm sipp_standby8_dispatch --output runs/v9-wait8.json
```

V9默认中型和固定柱/设备，`--layers 8`控制双排层数，单排始终1层。卸货后返程本就可以被新单打断；新增有限待命仅在普通通行区安全延迟返程，到达固定额度便继续返H。原包依据隐藏订单数量停止待命的逻辑已替换，等待与最终返库均完整计账。新策略为实验选项；BCRD目前只支持返库模式，不自动组合待命。审核、反例、效果与复现见 [V6/V9评估](docs/v9-review.md)。

30个新留出场景中，8步待命平均空驶下降1.302%，F改善0.121%，但区间跨零且7例F退化，因此不替代默认返库。BCRD返库在新静态积压组平均F改善2.283%，留出合计改善0.761%；两种机制分别测试，尾部响应仍有取舍。

## 结构

```text
src/agv/
  core/                  不依赖算法的任务、版本与坐标类型
  warehouse/ rules/      静态仓库几何、场景校验、分版本业务合同
  orders/                独立订单发布器与流关闭事件
  world/                 唯一执行内核、任务状态、行程、预约表、命令网关
  planning/              A*、SIPP、静态距离、取送路线组合与联合修复
  policy/                派单 / 空闲定位 / 修复策略与可见订单推演
  runner/                唯一求解循环、执行依赖编配
  registry.py            SolverSpec 组合及全部历史算法名
  evaluation/            由轨迹生成指标、离线评分、独立验解与下界
  learning/ models/      可解释排序器、训练流程与模型
  io/ experiments/       原子持久化、场景导入与冻结配对实验
  web/ cli.py            网页与命令行入口
  domain.py simulation.py dispatch/  历史导入兼容层

tests/golden/            重构前冻结的580次轨迹与全字段回放门禁
tests/unit/ integration/ 合同、回归、命令行和HTTP测试
examples/ data/          示例、公开地图与许可
docs/ results/           架构、研究与历史实测证据
runs/                   本机生成输出，不提交
```

本轮重构保持23个算法名、业务规则、默认值与历史结果格式；生产代码依赖方向由CI强制检查。运行 `python scripts/check_architecture.py` 检查结构，运行 `python tests/golden/record.py replay` 对照重构前580次金标准。实现与实测边界见 [重构验收记录](docs/architecture-refactor.md)，各模块职责见 [架构与接口边界](docs/architecture.md)。工程参考实际检查了 [w9-pathfinding](https://github.com/andreyd41/w9-pathfinding)、[作者MAPF-LNS](https://github.com/Jiaoyang-Li/MAPF-LNS)、[作者RHCR](https://github.com/Jiaoyang-Li/RHCR) 和 [libMultiRobotPlanning](https://github.com/whoenig/libMultiRobotPlanning)，固定源码版本与具体借鉴见 [研究记录](docs/research/engineering-and-sipp.md)。

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

这个已有模型来自旧规则数据，没有在 V4/V9 分层与专用交付点规则上重新训练或证明其收益；两版正式对照均不使用 `sipp_learned`。

```bash
agv train --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-training
agv benchmark --seeds 10 --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-evaluation
```

## 实验与验证

V4 对照见 [集成审核与实测](docs/v4-review.md)，逐次成绩、源码哈希和精选轨迹在 `results/v4/`。旧规则完整对照和负面结果见 [v2实测报告](docs/v2-results.md) 与 `results/v2/`；v1统计在 `results/v1/`。不同布局、服务与评分规则的成绩分开解释，不直接横向合并。只保留精选轨迹，其他结果可用固定输入、种子及命令重新生成。

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -t . -v
ruff check src tests
ruff format --check src tests
python -m build --wheel
```

已配置 Linux/macOS/Windows、Python3.10/3.12 测试，以及wheel安装后从源码目录外运行的检查。具体状态以GitHub Actions结果为准。更多复现及输出口径见 [复现指南](docs/reproduction.md)；开发约束见 [CONTRIBUTING](CONTRIBUTING.md)。

核心规则、初始贪心、时空A*、原验解器以及 V4 分层几何模型来自队友项目；新增工程结构、规划改进、V4 规则集成与修复、训练和实验证据属于本次适配。来源与许可边界见 [NOTICE](NOTICE.md)。组员真实姓名、学号和实际贡献比例需据实填入正式课程报告。

算法接入前请先阅读[建模框架系统审查与接口合同](docs/framework-audit-20261017.md)。本轮覆盖生命周期、状态验解、异常导入、历史代表轨迹和参数边界；实际运行证据及未覆盖范围见[审查证据目录](results/framework-audit-20261017/README.md)。它不构成任意场景无缺陷或全局最优证明。
