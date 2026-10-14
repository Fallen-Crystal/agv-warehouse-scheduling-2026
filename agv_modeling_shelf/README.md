# 本次算法增强版本（2026-10-14）

本目录保留队友原有内容，并增加可解释的途中联合后缀重规划。当前使用方式、正式成绩和限制以 [算法实现与实验报告](算法实现与实验报告.md) 与 [项目根 README](../README.md) 为准；下文是原版本说明，提到“尚不能途中改路”的句子描述原基线。

运行 `python3 show_warehouse.py` 可选择队友原版、仅匹配、仅重规划及融合算法。推荐“仅联合重规划”；完整 240 次配对实验在 `algorithm_results/`。

---

# 货架取货版：任选合法停靠侧，大仓库四列货架

本独立版本目录为agv_modeling_shelf。优先读《货架取货改动说明.md》。新订单指定shelf，车辆选择相邻合法位置装载，货架本体不可进入，同一货架格的不同侧允许同时装货；大仓库25×19格有四列货架。运行show_warehouse.py查看。新版页面仅接受货架格订单，旧固定取货点文件请用旧版打开；底层接口保留兼容用于验证。新输入不能交给旧版本。

本目录继承原agv_modeling_repro的保存、加载、批量实验和失败记录功能。原基础版、复现实验版和可选紧急任务版保留不变；没有加入待命和紧急程度。右键运行show_warehouse.py使用页面功能；右键运行batch_experiments.py将批量结果直接保存到独立输出目录。

本包独立于之前的算法原型，可以直接交给算法同学。先看《建模说明.md》，再看《算法接口说明.md》。Python 3.10 或更新版本，只使用标准库，不需要安装训练框架。

## 看仓库地图和车辆怎么走

在PyCharm或VS Code打开本目录，右键运行 show_warehouse.py，会自动打开本机浏览器页面。不必安装额外包，也不访问外部网站。保持这个Python程序运行，独立选择仓库大小、车辆数、通道、动静态、到达方式、需求热点、交付点、任务数量、种子和时限，再点击“生成并运行”。生成的是选定组合的真实模型轨迹，随后可播放、逐步查看、拖动时间条。

如果浏览器没有自动打开，在PyCharm输出中找到 http://127.0.0.1:端口/ 地址，在浏览器打开。点击PyCharm的停止按钮会关闭页面计算服务，之后不能继续生成新场景。

双击《仓库地图与轨迹.html》只能查看保存的默认结果；独立参数重新计算需要使用运行 show_warehouse.py 后打开的页面。点击方格可查看地图四邻接位置，动态任务释放前不显示取送点。

### 第一项改进：场景配置

example() 新增可选参数 vehicles=1…8、size='small'/'medium'/'large'（13×11、19×15、25×19），delivery_pattern='distributed'/'shared'。task_count 设置任务数量；layout 仍为 wide/bottleneck。默认参数与第一版一致。例：

```python
scenario = example(mode='dynamic', size='medium', vehicles=6,
                   task_count=30, delivery_pattern='shared')
```

这里“仓库变大”同时拉长货架和通行距离，不应声称是仅改变面积的单因素实验。改变车辆数时，专属停车位数量也会改变；需要在实验中记录这项布局变化。集中/分散交付使用相同取货样本，集中交付时任务全送往左侧一个服务点。

第2项新增 arrival='batch'/'uniform'/'irregular'/'burst'、demand='balanced'/'left_hotspot'/'right_hotspot'/'switching'、horizon参数，细节见《动态订单说明.md》。浏览器控件与模型通信、脚本语法已检查，实际浏览器点击播放未现场核验。

第3项新增最长与P90响应时间、时间分解、空驶与载货距离和逐车工作量。页面下方查看统计表，并可下载汇总/每车/每单CSV。计算口径及失败处理见《评价指标说明.md》。五项改进现在完成前三项；本项不改变调度行为。

## 运行

在本目录打开终端：

```text
python -m unittest -v test_model
python -m unittest -v test_metrics
python -m unittest -v test_viewer
python run_examples.py
python run_dynamic_examples.py
python audit_examples.py
```

第二条重新生成 examples 下的四组固定样例、轨迹、汇总及源代码校验信息，会覆盖同名文件。需要保存旧结果时先复制到另一目录。

查看输入可用 model.Scenario.from_dict 读取 JSON；要接入自己的算法，参考《算法接口说明.md》中的最小调用。策略只读取 observe()。

## 文件职责

| 文件 | 内容 |
|---|---|
| 建模说明.md | 假设、静态/动态定义、目标、约束、状态、局限 |
| 算法接口说明.md | 观测、动作、失败规则、指标、算法接入 |
| model.py | 地图、任务、输入检查与样例 |
| environment.py | 任务释放及逐步执行、锁定、重派、日志 |
| routing.py | 参考时空 A* 与预约检查 |
| baseline.py | 演示用距离贪心策略与运行循环 |
| validation.py | 独立轨迹、服务、容量、释放及指标校验 |
| test_model.py | 模型规则与反例检查 |
| run_examples.py | 生成输入、轨迹和结果汇总 |
| show_warehouse.py | 生成独立地图及轨迹查看页面 |
| test_viewer.py | 检查独立选项与本机模型计算服务 |
| run_dynamic_examples.py | 保存和复核16种动态组合 |
| 动态订单说明.md | 到达规则、热点定义与本版使用方式 |
| metrics.py | 新增评价指标及每车、每单统计 |
| test_metrics.py | 人工答案、边界情况及错误指标检测 |
| export_metrics.py | 保存和复核每车、每单CSV |
| 评价指标说明.md | 指标口径、失败场景解释及报告分析思路 |
| audit_examples.py | 重新读取保存样例并复核轨迹、汇总及源代码摘要 |
| 验证记录.md | 当前运行验证证据及解释 |
| 实施计划.md | 本版实施范围和验收顺序 |

四组样例：static_wide、static_bottleneck、dynamic_wide、dynamic_bottleneck。静态/动态使用相同12个取送任务，动态只改变释放时间；两种地图改变中央通道数量。完整动态输入用于评测，禁止在线策略预读未来订单。

目前只验证模型可以运行及输出轨迹满足规则，未实现或验证 DQN、匈牙利算法、需求预测。参考路径规划按优先级预约，不能保证全局最优或所有可行输入必定成功。详情见建模说明。

## 车辆迎面避让

双击《车辆迎面避让演示.html》可看入口等待、侧边让行、没有错车位置三种情况，离线即可播放。路线来自现有时空A*，演示只含局部行驶，不是完整订单成绩，也不是训练结果。正式模型在接单时根据正在运行车辆已排的路线安排等待或绕行，随后执行；不在途中临时改动其他车辆已锁定的任务路线。完全没有让行位置时，固定预约规划可能失败，需要算法同学重新协调优先次序或路线，不能保证任意迎面冲突都能解决。
