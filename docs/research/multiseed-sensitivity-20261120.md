# 多 seed 与超参数对照实验

本轮按固定主实验之外补充稳定性和参数图的思路，固定 `ea719b5` 的推荐运行时，比较同一规则和同一输入下的方案演进、计算预算与自适应遗传算子。完整记录在 `results/sensitivity-20261120-v2/`，正文和图片在该目录的 `report/`。

## 实测结论

正式 200/200 次全部有效，累计执行 10,050 次订单服务；唯一源请求仍为 201 条。封存 ZIP 后，使用固定独立验解器再次检查全部 200 条完整轨迹，全部有效。以下 F 改善率先在日期内对相同 seed 配对，再对 4 个日期等权平均；CPU 变化使用同一配对集合的平均 CPU 比值。

|候选 / 对照|配对 seed|F 改善率|CPU 变化|胜/平/负日期|
|---|---|---:|---:|---|
|wide / simple|0–4|+0.988%|+84.58%|3/1/0|
|gate / wide|0–4|+0.112%|−3.34%|1/3/0|
|hga / gate|0–4|+0.946%|−8.68%|2/1/1|
|preview=3 / gate|0–2|−0.683%|−45.28%|0/2/2|
|自适应变异 / 固定双概率|0–2|+0.054%|+1.25%|2/0/2|
|自适应交叉 / 固定双概率|0–2|+0.938%|−4.22%|3/1/0|
|双自适应 / 固定双概率|0–2|+0.234%|−1.46%|2/0/2|

结果支持以下技术判断：

1. **匈牙利初始化值得后续验证。** 它没有增加种群或完整预演上限，平均 F 更低，日期内 seed 标准差的均值由 0.01378 降至 0.00355。但其日期 bootstrap 改善区间为 `[−0.302%, 2.272%]`，且一个日期退化，不能据此替换默认方案。按平均物理指标分解 ΔF，约 76% 的收益来自完工时间 T 的加权项，响应和里程也有贡献。
2. **完整预演是更有效的计算预算旋钮。** 6→3 次预演明显节省 CPU，但存在 F 代价。仅把 proxy 上限降到 96，F 平均退化 0.770%，CPU 反而增加 2.70%；仅把代数 16→8，F 退化 1.041%，CPU 增加 0.32%。这与完整 SIPP 轨迹预演占据主要成本的解释相符；不能把这些干预结果当成精确的 CPU profiling 占比。
3. **两个自适应机制不具可加性。** 在同一算子四格中，只开交叉自适应表现更好；只开变异的净收益接近零，同时开启也没有叠加单项收益。双自适应的 5,360 代记录中，4,640 代变异率已达到上限 0.95（86.57%），335 次搜索均至少饱和一次；这个机制在本批输入中大部分时间相当于高变异，难以持续体现细粒度调节。双自适应相对固定四格对照的平均窗口 P90 增加 14.75 步；F 的小幅收益不能代表尾部同时改善。
4. **低负载门控的作用取决于工况。** day45 的 gate 及预算变体均未启动 GA，指标完全一致；这里改 GA 超参数没有影响。其余日期必须结合实际搜索次数和参数上限触发情况解释。

变异率饱和也有直接的公式解释：`pm = clip(0.7 * (1 + 0.2*s + 0.6*(1-d)), 0.05, 0.95)`。当停滞计数 `s >= 2` 时，即使多样性 `d=1`，未裁剪值也达到 0.98，因此必然被截到 0.95。它支持优先审查增长斜率和饱和机制的后续实验，但现有四格不能把所有效果差异归因于饱和本身。

当前保留原默认 gate。本轮将 hga、单独自适应交叉和低预算 preview=3 作为下一阶段候选，分别验证初始化、算子控制和计算预算折中；四个历史开发日期不承担新验证集的角色。CPU 绝对值为 Apple M5、10 逻辑 CPU、24 GiB 内存上 Python 3.12.13 的本地测量。

## 比较范围

主矩阵共 200 次：

|组别|方案|每窗 seed|次数|
|---|---|---|---:|
|规则对照|FCFS、ETA、Hungarian|0、1；核查确定性|24|
|演进比较|simple、wide、gate、hga|0–4|80|
|预算干预|proxy=96；preview=3；两者同时；generations=8|0–2|48|
|算子消融|固定/自适应变异 × 固定/自适应交叉|0–2|48|

共同模型为 large 62×47、6 辆车、5 层、SIPP 预约避碰。固定原开发窗口 day12/bin1164、day32/bin3113、day33/bin3229、day45/bin4335，共 201 条唯一源请求。WEPAStacks 真实订单片段经过项目规则映射，货位映射 seed 固定为 17；这不构成原 WEPA 地图或整仓的工业复现。

目标始终为 `F = 0.5*T/900 + 0.3*R/900 + 0.2*D/5400`。T 为最后订单完成时刻，R 为完成减发布的平均响应，D 为所有移动格数；D 包含关闭订单流后的最终返库，T 不包含最终回库完成时刻。P90、空驶、交通等待另行报告。

`simple` 是早期线性目标 GA，使用原 `LinearPolicy`；`wide` 扩大整组搜索预算；`gate` 在流未关闭且未派订单不多于空闲车时改用即时精确批匹配；`hga` 以匈牙利方案替换两个随机初始个体；独立 `hungarian` 优化当前固定边估计上的线性代理，再由 SIPP 提交。局部路径、固定矩阵上的精确性不能推广为多车动态全局最优。

预算实验固定其他配置，对照 `(proxy, preview, generations)` 的 `(192,6,16)`、`(96,6,16)`、`(192,3,16)`、`(96,3,16)`、`(192,6,8)`。同时记录实际评分、预演次数及上限触发，区分预算上限与实际工作量。

自适应四格将后续 `adaptive_genetic.py` 算子迁入相同 `wide` 策略环境，固定种群 12、精英 2、初始 pm=0.7、pc=0.9，只改变两个自适应开关。`wide_adapt00` 是该四格的固定概率对照。原 wide 的交叉流程与该新算子也有差异，因此 `wide_adapt11 / wide` 是整组算子移植比较，不能解释成单独一个自适应机制的贡献。

## 统计与验解

- seed 控制搜索随机性，不改变订单流或构成独立物理场景。同窗先平均 seed，再按来源日期等权汇总；统计独立单位只有 4 个日期。
- 相同 seed 标签不保证不同算子消耗相同的随机数序列。表中的 P90 是窗口内 P90 再按日期平均，不是将全部重复任务合并计算的单一分位数。
- 配对使用事先声明的 case/seed 交集；所有计划运行、失败和中断保留。失败不会缩小比较分母，缺失或失败使相应比较 `incomplete`。
- F 改善率正值表示候选更低。日期 bootstrap 95% 区间仅作描述，4 个历史开发日期不支持显著性或新日期泛化声明。
- 每次运行由原独立验解器检查完整轨迹后计分；运行前后核对输入和源码哈希。摘要必须与 gzip 轨迹中的物理指标、评分和搜索记录一致。
- CPU 是单个模拟进程的累计计算耗时，不是 AGV 物理时间或每次决策的最坏延迟；顺序使用固定种子随机打乱，最多并行两个实验进程。
- 权重图只对同一批合法轨迹重新评分，未按新权重重新优化。
- 本轮不是 DQN 多初始化 seed 重训；不能用这些 GA 结果推断网络训练稳定性。历史 DQN 小时窗结果也不与本轮 15 分钟窗口的绝对 F 混排。

最初 5/200 次预检因评测脚本格式和 Windows 导入兼容性修正而中止，原计划、日志与结果保留在忽略目录 `runs/sensitivity-20261120/aborted-preflight-study/`；正式 v2 固定原参数和日期，全矩阵重新执行，预检结果不进入统计。

## 复现

以下命令从仓库根目录执行，输出位置必须尚不存在：

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
uv run --no-project --python 3.12 --with reportlab==4.4.9 python \
  scripts/build_sensitivity_pdf.py results/my-sensitivity \
  --output output/pdf/my-sensitivity.pdf
```

`prepare` 校验原 ZIP 清单，再覆盖固定提交的当前可读源码，运行时只展开到忽略目录 `runs/`。原生产结构和默认配置保持不变。复现新实验会生成自己的绝对路径、时间、CPU 和清单哈希；业务指标按相同输入、参数和 seed 比较。

公开的 `trajectories.zip` 只包含本轮压缩轨迹。便携 `verify` 依靠研究目录内的清单、摘要和 ZIP 即可校验记录一致性，不依赖作者电脑上的绝对路径。它不等于重新执行物理验解；物理验解由各次原运行的 `objective.checked_score` 执行。`evidence.json` 封存原始输入记录和文件指纹，报告单独生成。

另提供历史 DQN 最小运行时准备入口 `--kind dqn`，保留原模型及源码检查，不将完整旧包放回生产树。浅克隆需要先获取固定历史对象：

```bash
git fetch origin ed2bd0a96930ea042aab31b845f1c8cc06dcc55d
.venv/bin/python scripts/prepare_sensitivity_runtime.py \
  --kind dqn --main-ref ea719b598662707c67f9d93b990812d4e45e24cd \
  --output runs/my-dqn-runtime
```

数据来源和 MIT 许可保留在 `research/recommended-20261024/data/raw/`；本轮运行时归档、当前源码覆盖和案例身份逐项记录于 `plan.json`。不同模型或不同窗口的旧数值作为历史背景保留，不作为本轮新运行证据。
