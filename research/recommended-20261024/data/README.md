# 原始真实请求与映射边界

采用 [SLAPStack作者仓库](https://github.com/malerinc/slapstack/tree/da6280a8f8be1010eae64264c69a90258a288173) 的 WEPAStacks，用例来自WEPA纸品仓储业务。固定源提交、原文件SHA256和字节数见 source-manifest.json；原README和MIT许可随附。数据关联论文：Pfrommer等，*SLAPStack: A Simulation Framework and a Large-Scale Benchmark Use Case for Autonomous Block Stacking Warehouses*，ICCL 2022，DOI [10.1007/978-3-031-16579-5_20](https://doi.org/10.1007/978-3-031-16579-5_20)。来源字段和开放数据声明以作者资料为依据，不把公开数据等同于本项目采集的工业执行日志。

完整原订单411,830条随包提供，无删行、重采样或人为注入突发单。为减少仓库体积，以无损gzip保存；执行 `python data/unpack.py` 即还原原始40,119,428字节JSON，并核对全部文件哈希。原始布局也保留作出处参考，本实验不使用原厂堆垛布局。

每行六列：`[kind, sku, arrival_abs_seconds, dock, batch, week]`。delivery=入库，retrieval=出库；一条请求对应一单位托盘/货物运输，不是一个电商购物订单。没有可靠的实测AGV路径、车辆分配、装卸耗时、订单完成时间、紧急程度或本模型F，不能据此计算“原厂F”作比较。

当前主实验采用自然部分重叠的入库/出库流：保留原始类型、SKU、到达时刻及相同时刻的全部请求；不要求每个时刻入出库同时发生，不强制配对一进一出。划分900秒半开窗口 `[start,start+900)`，相对发布时间为原时刻减start，不压缩时间。

模型映射在完整包 baseline/engine/wepa/data.py：固定种子17分配SKU到合法货架格；每个SKU按初始库存加固定50格余量配置存储空间，不用未来需求量来选位置；对应端口以 `(source_dock-1) % 端口数` 映射。初始库存由原始初值加窗口前全部入出库请求的净变动重建，假设之前作业已完成，非原厂在制品/时延实测。库存更新仍以本模型的物理取放完成事件为准。

八个当前窗口及初始库存、源行号、任务列表见 current/evidence/data/protocol.json。四个开发窗口固定；四个验证窗口未在该轮求解前使用，但日期曾出现在早期研究中，因此只称“新窗口验证”，不称独立新日期外部验证。输入筛选为35–65条、2–5个SKU、两类任务各至少5条、有限初始库存及非负台账；历史各轮条件以各自冻结协议为准。此筛选不是全部原始业务场景，也不是全SKU压力测试。

地图、层数、同构车速、装卸时间、取放层序、待命和返库均为课程建模设定。当前结果应称“真实请求驱动、模型内仿真”，不能称真实仓库部署或实测节能。
