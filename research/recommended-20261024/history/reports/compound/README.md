# 同时换车与重排的调度实验

详细结果与方案设计请参阅 [结果报告.md](结果报告.md) 和 [实验设计.md](实验设计.md)。本阶段在保持原有仓库模型与独立线性目标 `F` 的前提下，研究“同时换车与重排”的复合邻域搜索与联合 GA 的组合效果，底层路径均由原 SIPP 生成。

## 主入口（Python 3.12 标准库）

在解压后的研究包根目录运行：

```powershell
python run_main.py --case wepa-day38-bin3708 --output new-result.json
python run_main.py --case wepa-day38-bin3708 --profile compound --output compound-result.json
```

输出文件须为新路径（默认拒绝覆盖已有文件），每次运行输出完整轨迹、独立评分与源码指纹。包内辅助脚本包括：`run_trial.py`（单次对照）、`batch.py`（双进程批量运行）、`select.py`（开发集选型）与 `analyze.py`（独立重验与汇总生成）。

## 核心模块与配置说明

- `improved/compound.py`：生成同时换车与重排的复合邻域候选；
- `improved/policy.py`：控制 GA 与复合邻域的代理预算及完整预演分配；
- `improved/profiles.py`：定义 `gate`、`compound`、`compound_only` 三组正式实验配置（另保留历史回归配置）；
- `baseline/`：191 个冻结基线依赖文件。

三组方案的准确标识以 `profile` 字段为准（详见包内 `data/algorithm-labels.json`）。注：冻结源码的原始日志字段 `search_log.optimizer` 沿用了旧标签 `joint_ga`，在 `compound_only` 配置下 GA 预算为 0（跳过 GA 仅执行复合邻域），报告与统计表均按准确的 `profile` 区分。

## 测试与数据范围

- `python -m unittest test_compound -v` 仅需 Python 标准库；完整 29 项测试额外包含微型两车 CP-SAT 参照检验，需安装可选依赖 `pip install -r requirements-exact.txt`。`micro_check.py` 复用既有已证最优微型案例开展机制回归。
- 验证集包含 4 个未测试的 900 秒真实请求窗口（每方案 2 个随机种子，以 4 个来源日期为统计单位；来源日期的其他时段曾在早期实验出现），运行环境固定为大型 62×47 地图、6 车、5 层课程仿真仓库。
- `data/protocol.json` 已内置全部选中订单与窗口初始库存；若需与完整 41 万条源订单核验，可配合原始数据执行 `verify_input.py --raw <原始文件目录>`。
