# 原始真实请求与仿真映射说明

本项目采用的真实订单请求来自 [SLAPStack 作者仓库](https://github.com/malerinc/slapstack/tree/da6280a8f8be1010eae64264c69a90258a288173) 中的 **WEPAStacks** 公开数据集（源于 WEPA 纸品仓储业务）。固定源提交、原始文件 SHA256 与字节数记录于 `source-manifest.json`，随附原 `README.md` 与 MIT 许可。关联论文：Pfrommer 等，*SLAPStack: A Simulation Framework and a Large-Scale Benchmark Use Case for Autonomous Block Stacking Warehouses*，ICCL 2022，DOI [10.1007/978-3-031-16579-5_20](https://doi.org/10.1007/978-3-031-16579-5_20)。

完整原始订单共 411,830 条，以无损 gzip 格式归档以节省仓库空间；在材料根目录运行 `python data/unpack.py` 即可还原原始 40,119,428 字节 JSON 并自动核对全部文件哈希。原始仓库布局文件（`1_layout.csv`）一并保留作为出处参考，本实验在课程多层货架仿真网格上运行调度算法。

## 数据字段与窗口切分

原始订单每行包含六列：`[kind, sku, arrival_abs_seconds, dock, batch, week]`。其中 `delivery` 表示入库、`retrieval` 表示出库，每条请求对应 1 个标准托盘/货物单元的搬运任务。数据集提供真实请求到达时间、类型、SKU 与作业口信息，用于驱动本项目仿真模型中的 AGV 调度评估。

主实验保留入库与出库自然部分重叠的真实到达流，按 900 秒半开区间 `[start, start+900)` 切分窗口，相对发布时间为原始到达时刻减去窗口起点 `start`，保持真实时间间隔与并发批次不变。

## 仿真仓库映射规则

模型映射实现位于 `baseline/engine/wepa/data.py`：

- **货位映射**：采用固定随机种子 `17` 将各 SKU 映射至合法货架格；每个 SKU 按初始库存加 50 格固定余量分配存储空间（仅依赖初始状态）。
- **作业口映射**：按 `(source_dock - 1) % 端口数` 映射至仿真仓库的入库口与出库口。
- **初始库存重建**：由原始初始库存加上窗口起始前全部入/出库请求的净变动量推算得到，后续仿真过程中严格在物理取放完成事件发生时更新库存。

当前 8 个窗口（4 个开发窗口、4 个新窗口验证）的初始库存、源行号与完整任务列表均已固化于 `current/evidence/data/protocol.json`。窗口筛选条件为：35–65 条请求、2–5 个 SKU、入出库各至少 5 条、有限初始库存及非负库存台账。

仓库地图尺寸、货架层数、车速、装卸耗时、上下层取放顺序、安全待命与最终返库均采用统一的课程仿真参数设定，构成“真实订单流驱动的仿真实验环境”。
