# WEPA 开发窗多 Seed 稳定性与超参数敏感性实验报告

本实验固定提交 `ea719b5` 的推荐运行时，在同一仓库规则与输入窗口下系统评估了算法演进、计算预算分配与自适应遗传算子三组对照。完整原始记录与图表保存在 [`results/wepa-dev-sensitivity-20261120/`](../../results/wepa-dev-sensitivity-20261120/REPORT.md)（正文为 `REPORT.md`，图表在 `figures/`）。

## 1. 核心实测结果与技术发现

正式实验矩阵全部 **200/200 次运行均有效完成**，累计执行 **10,050 次**订单服务（覆盖 4 个开发日期窗口的 201 条唯一源订单请求）；封存 `trajectories.zip` 后，通过独立验解器复核全部 200 条完整轨迹均合法通过。

下表汇总各组核心配对表现（`F` 改善率采用日期内同 seed 配对后再跨 4 个日期等权平均，正值表示 `F` 更优；CPU 变化为同一配对集合的平均 CPU 比值变化）：

| 候选 / 对照 | 配对 seed | `F` 改善率 | CPU 变化 | 胜 / 平 / 负日期 |
|---|---|---:|---:|---|
| `wide` / `simple` | 0–4 | +0.988% | +84.58% | 3 / 1 / 0 |
| `gate` / `wide` | 0–4 | +0.112% | −3.34% | 1 / 3 / 0 |
| `hga` / `gate` | 0–4 | +0.946% | −8.68% | 2 / 1 / 1 |
| `preview=3` / `gate` | 0–2 | −0.683% | −45.28% | 0 / 2 / 2 |
| 自适应变异 / 固定双概率 | 0–2 | +0.054% | +1.25% | 2 / 0 / 2 |
| 自适应交叉 / 固定双概率 | 0–2 | +0.938% | −4.22% | 3 / 1 / 0 |
| 双自适应 / 固定双概率 | 0–2 | +0.234% | −1.46% | 2 / 0 / 2 |

四项关键发现如下：

1. **匈牙利初始化（`hga`）同时提升了质量均值与多 seed 稳定性**：在不增加种群规模与完整预演上限的前提下，`hga` 相对 `gate` 平均改善 `F` **+0.946%** 并节省 **8.68%** CPU，且日期内 seed 标准差的均值由 **0.01378 大幅降至 0.00355**。按物理分项拆解，约 **76%** 的 `ΔF` 收益来自完工时间 `T` 的加权项，响应与里程同步贡献正向收益。由于 4 日期 bootstrap 区间为 `[−0.302%, 2.272%]` 且存在 1 个日期轻微退化，当前将其列为下一阶段独立验证集上的重点候选（参见后续验证集实验），暂维持 `gate` 为默认入口。
2. **完整轨迹预演次数（`preview`）是最灵敏的计算预算旋钮**：将完整预演上限由 6 降至 3 可节省 **45.28%** CPU，对应 `F` 代价为 −0.683%。相比之下，仅将代理评分上限 `proxy` 降至 96 会使 `F` 退化 0.770% 且 CPU 反而增加 2.70%；仅将迭代代数从 16 减半至 8 会使 `F` 退化 1.041% 且 CPU 增加 0.32%。这一对比清晰反映出完整 SIPP 轨迹预演在总计算开销中占据主导地位。
3. **两项自适应遗传算子存在交互干扰，单独自适应交叉表现最佳**：在同环境四格消融中，仅开启自适应交叉取得 **+0.938%** 的 `F` 改善与 **−4.22%** 的 CPU 节省（3 胜 1 平）；而仅开启自适应变异净收益接近零（+0.054%），两者同时开启后收益反而回落至 +0.234% 且平均窗口 P90 上升 14.75 步。日志剖析揭示了直接原因：在双自适应的 5,360 代记录中，有 **4,640 代（86.57%）** 的变异率触发了上限 `0.95`，全部 335 次搜索均至少饱和一次。按公式 `pm = clip(0.7 * (1 + 0.2*s + 0.6*(1 - d)), 0.05, 0.95)`，只要停滞计数 `s >= 2`，即使种群多样性 `d = 1`，未裁剪值也会达到 `0.98` 而被截断至 `0.95`，导致该算子在多数代数退化为持续高变异。
4. **低负载门控（`gate`）按工况自动生效**：在轻负载窗口 `day45` 中，`gate` 及其预算变体全程走即时精确批匹配、未启动 GA，各变体指标完全一致，避免了无谓的进化搜索开销。

以上发现明确筛选出 `hga`、单独自适应交叉以及低预算 `preview=3` 作为下一阶段独立留出验证的候选配置。本轮 CPU 测量环境为 Apple M5（10 逻辑 CPU、24 GiB 内存、Python 3.12.13）。

## 2. 实验矩阵与配置设计

全部 200 次正式运行分为四组：

| 实验组 | 参测配置 | 每窗 seed | 运行次数 |
|---|---|---|---:|
| 规则基线 | `FCFS`、`ETA`、`Hungarian` | 0、1（核验确定性） | 24 |
| 方案演进 | `simple`、`wide`、`gate`、`hga` | 0–4 | 80 |
| 预算干预 | `proxy=96`、`preview=3`、`proxy=96+preview=3`、`generations=8` | 0–2 | 48 |
| 算子消融 | 固定/自适应变异 × 固定/自适应交叉（四格） | 0–2 | 48 |

**统一模型与目标口径**：
- 地图为大型 `62×47`、6 辆车、5 层货架、SIPP 预约避碰；输入固定为 4 个 WEPAStacks 开发片段（`day12/bin1164`、`day32/bin3113`、`day33/bin3229`、`day45/bin4335`，共 201 条唯一订单，按项目货位映射规则 seed 17 转换）。
- 目标函数统一为 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`（`T` 为最后订单卸货完成时刻，`R` 为平均响应时间，`D` 为含最终返库的总移动步数），同步汇报窗口 P90、空驶里程与交通等待。
- 演进链路中：`simple` 为早期线性目标 GA（`LinearPolicy`）；`wide` 扩大搜索预算；`gate` 在流未关闭且待派订单不多于空闲车时切换为即时精确批匹配；`hga` 在 `gate` 基础上以匈牙利方案替换两个随机初始个体。
- 预算实验围绕 `(proxy, preview, generations)` 的五组设定 `(192,6,16)`、`(96,6,16)`、`(192,3,16)`、`(96,3,16)`、`(192,6,8)` 同步记录实际评估数、预演数与上限触发次数。
- 算子消融将 `adaptive_genetic.py` 迁入统一 `wide` 策略框架（种群 12、精英 2、初始 `pm=0.7`、`pc=0.9`），以 `wide_adapt00` 作为四格固定概率基线，单独隔离变异与交叉自适应开关的影响。

## 3. 统计口径与过程审计

- **汇总单位**：多 seed 用于刻画随机搜索的内部方差；统计汇总时先在同窗口内对 seed 取均值，再跨 4 个来源日期等权平均，日期 bootstrap 95% 区间用于描述 4 日期内的波动范围。窗口 P90 先在单窗内计算再按日期平均。
- **完整性与验解**：所有配对使用预设的 case/seed 交集，每次运行均由独立验解器校验完整轨迹后计分，并核对输入与源码指纹以及 gzip 轨迹和汇总表的一致性。CPU 为单次仿真进程累计耗时，实验顺序经固定种子随机打乱，最多 2 个进程并行。权重敏感性图基于同一批合法轨迹重算展示。
- **预检与正式分离**：此前 5/200 次预检因脚本格式与 Windows 导入兼容性调整中止并归档至 `runs/sensitivity-20261120/aborted-preflight-study/`；正式实验固定全套参数重新完整执行 200 次。
- **跨平台一致性校验**：后续 Windows CI 修复了 ZIP 成员路径检查；核验确认修复后准备的 329 个运行时文件与本轮正式实验所用文件逐字节一致，记录见 `runtime-preparation-followup.json`。

## 4. 完整复现命令

以下命令在仓库根目录执行（输出目录需为全新路径）：

```bash
git fetch origin ea719b598662707c67f9d93b990812d4e45e24cd
uv sync --python 3.12 --locked --all-extras

.venv/bin/python scripts/prepare_sensitivity_runtime.py \
  --kind recommended --main-ref ea719b598662707c67f9d93b990812d4e45e24cd \
  --output runs/my-sensitivity/recommended
.venv/bin/python scripts/run_sensitivity_study.py init results/my-sensitivity \
  --runtime runs/my-sensitivity/recommended
.venv/bin/python scripts/run_sensitivity_study.py run results/my-sensitivity --workers 2
.venv/bin/python scripts/run_sensitivity_study.py verify results/my-sensitivity --traces
.venv/bin/python scripts/report_sensitivity_study.py results/my-sensitivity

.venv/bin/python scripts/verify_sensitivity_evidence.py seal results/my-sensitivity
.venv/bin/python scripts/verify_sensitivity_evidence.py verify results/my-sensitivity
```

说明：`prepare_sensitivity_runtime.py` 会先校验归档清单再覆盖固定提交源码至临时目录 `runs/`，保持主干生产代码不变。公开的 `trajectories.zip` 与 `evidence.json` 支持跨机器离线核验记录完整性（真实物理验解由每次运行的 `objective.checked_score` 执行）。数据来源与 MIT 许可保留在 `research/recommended-20261024/data/raw/`。

如需单独准备历史 DQN 最小运行时（与本轮 GA 15 分钟窗实验分开独立复核），可执行：

```bash
git fetch origin ed2bd0a96930ea042aab31b845f1c8cc06dcc55d
.venv/bin/python scripts/prepare_sensitivity_runtime.py \
  --kind dqn --main-ref ea719b598662707c67f9d93b990812d4e45e24cd \
  --output runs/my-dqn-runtime
```
