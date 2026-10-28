# 仓库AGV：简化诊断与搜索改善版

先读`docs/诊断与改进报告.md`。本次没有更换地图、放宽库存/层序或修改评价权重，而是用对照实验检查简化环节，再在新窗口验证选中的方案。

## 选定主线

1. **订单流尚未关闭且负载低**：当可见待处理订单数不超过当前空闲车辆数，用当前预计边代价的精确最小成本批次匹配；真实路径仍由SIPP检查。不等待忙车来执行一个很小的已知批次。
2. **有积压**：联合GA搜索订单优先顺序和车辆归属，软分区只引导候选，不禁止跨区。最多192个代理评估、6次完整可见任务试排，GA最多16代；不额外叠加ACO、PSO或事后修复器。
3. **真实路径与执行**：原SIPP＋预约表解决多车占用，执行当前动作；新订单到达后滚动重规划。批次之间按原安全待命规则，真实订单流结束且任务完成后最终返库。

固定主目标仍为`F=0.5T/900+0.3R/900+0.2D/5400`。T/R以秒计，D以格计，主场景6车、速度1格/秒。不存在其他算法作分母。F不保证在0–1之间，也没有统一的0.8合格线。

选定方案由`results/selection.json`在验证前冻结，代码哈希必须匹配。轻负载匹配只对当前估计指派子问题精确，不代表整段动态任务全局最优。6个单车静态子问题有独立精确参照；主6车动态系统没有最优性证书。

## 可运行入口

Python 3.12，无额外第三方依赖。从任意目录运行入口，输出使用未存在的新文件名：

```text
python run_main.py --case wepa-day75-bin7248 --seed 0 --output my-run.json
python run_trial.py --case wepa-day75-bin7248 --profile simple --seed 0 --output simple-run.json
python -m unittest test_variants -v
```

`run_trial.py`暴露所有诊断对照；`run_main.py`始终使用开发集选定的方案，不根据新窗口重新选。

## 文件与证据

- `baseline/`：完整保留上一版191个文件；SHA256见`data/baseline-manifest.json`。
- `improved/`：诊断变体和选定算法；原物理内核位于baseline，不修改。
- `data/protocol.json`：场景、目标、种子、输入筛选、资源限制；后续两个变体的预声明见docs/第二阶段假设.md。
- `results/dev-components/`、`results/dev-guided/`：全部24次开发变体执行，包含负面结果。
- `results/validation/`：4个新窗口的配对验证；场景内先平均两个种子。
- `results/exact.json`和`results/exact-traces/`：缩减静态单车问题、DP证明和逐车验解。
- `results/*probe*.json`：精确前缀重放和被动诊断；没有把探针改善当成全程改善。
- `results/source-phases/`：第一阶段与最终选定阶段的源码快照；快照是证明材料，运行时用根目录入口和baseline依赖。
- `results/comparison.csv`：原始物理指标和综合成本。
- `select_windows.py`：只看原请求输入重现新窗口选择，不读算法成绩。

原始请求源为公开WEPA；本包只包含运行所需的已选窗口。原始数据说明、许可和源码贡献说明保留在baseline中。库存台账、货架位置和作业速度仍按课程模型设定，不声称复现原厂执行绩效。

没有修改旧ZIP或上传GitHub。其他地图、车数、层数未在本轮重新做全场景实验。
