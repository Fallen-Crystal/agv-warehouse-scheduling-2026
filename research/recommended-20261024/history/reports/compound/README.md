# 同时换车与重排的调度实验

阅读 [结果报告](docs/结果报告.md) 和 [冻结实验设计](docs/实验设计.md)。主算法是可见任务的联合GA/复合邻域搜索，路径由原SIPP产生。未改变仓库模型和线性F。不是全局最优求解器。

主入口（Python 3.12，标准库）：

```powershell
python run_main.py --case wepa-day38-bin3708 --output new-result.json
python run_main.py --case wepa-day38-bin3708 --profile compound --output compound-result.json
```

目标文件必须不存在，防止覆盖结果。每次结果包含完整轨迹、独立评分和源代码身份。`run_trial.py` 可运行单次；`batch.py` 用两进程运行预先冻结的分组；`select.py` 只在开发后、验证前选择；`analyze.py` 独立重验并生成 summary.json/comparison.csv。不能覆盖本包既有实验目录，重新实验应复制成新版本或使用新的 --phase 名。

核心新增：`improved/compound.py` 生成复合候选；`improved/policy.py` 决定GA与复合搜索预算及完整预演；`improved/profiles.py` 固定三组参数。`baseline/` 是191文件冻结依赖，不能当本轮默认算法说明阅读。

配置文件还保留早期实验的回归配置供旧测试使用。本轮实验及主入口只开放 gate、compound、compound_only 三种，不将其他配置串联。

算法标识读取 `profile`，三组精确含义见 `data/algorithm-labels.json`。冻结代码的原始 `search_log.optimizer` 字段沿用了粗略旧标签 `joint_ga`，在 compound_only 中不能据此判断用了GA；其GA预算为0，代码跳过GA。原始日志未事后改写，表格和报告均按准确的profile区分。

`python -m unittest test_compound -v` 仅用标准库。完整29项测试还包括旧两车最优求解器模块的检查，需要 `pip install -r requirements-exact.txt` 的可选OR-Tools依赖；它不用于六车主实验。`micro_check.py` 复用此前已证明最优的固定微型案例，仅做回归，不重新求解。

本轮验证为4个未测试窗口、每方案2随机种子，其来源日期已用于此前其他窗口实验。4个日期是分析单位，不能称为新日期外部验证。只验证大型62×47、6车、5层、900秒真实请求窗口；地理、服务与物理耗时是本模型仿真输出。

源请求文件未重复打包（41万行）；`data/protocol.json` 已含所有选中订单和窗口初始库存，因此主实验不需要原始文件。若已有相同哈希原始文件，可用 `verify_input.py --raw <原始文件目录>` 重建输入选择。
