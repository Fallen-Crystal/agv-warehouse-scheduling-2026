# AGV 当前推荐方案与研究材料总包（2026-10-24）

## 结论与入口

当前推荐 **事件驱动滚动派单＋软分区联合 GA＋预约表 SIPP（`gate`）**。在 4 个验证窗口（`day40/61/83/87`）上，2026-10 单 seed 0 平均 $F = 0.896406$；2026-11-21 扩展至 seed 0–2 的回顾性复评均值为 $F = 0.899159$（详见 [wepa-val-sensitivity-20261121](../../results/wepa-val-sensitivity-20261121/REPORT.md)），两者仅 seed 集合不同、结论一致。

```bash
uv run python research/recommended-20261024/current/run.py \
  --case wepa-day45-bin4335 --seed 0 --output runs/my-result.json
```

运行仅需 Python 3.12 标准库，输出文件已存在时默认拒绝覆盖。自 2026-11-02 起，实际运行源码位于 [current/code-guide/improved](current/code-guide/improved)（详见 [current/READABILITY.md](current/READABILITY.md)），包内 ZIP 文件用于冻结依赖与历史审计。完整测试与开发入口见 [current/README.md](current/README.md)。

## 阅读顺序与目录结构

建议阅读顺序：[数学模型与规则](docs/数学模型与规则.md) → [算法主线与接口](docs/算法主线与接口.md) → [阶段工作与实验比较](docs/工作与实验总览.md) → [结果报告](current/evidence/docs/结果报告.md) → [参考文献与借鉴边界](docs/参考文献与借鉴边界.md)。历史变更见 [CHANGELOG.md](CHANGELOG.md)。

| 目录 | 内容 |
|---|---|
| `current/` | 固定推荐入口、可读主线运行源码（`code-guide/improved`）、冻结源码 ZIP、协议与结果 |
| `data/` | 411,830 条 WEPAStacks 真实请求（无损 gzip）、初始库存、原布局、映射与哈希说明 |
| `docs/` | 数学框架、算法接口、阶段总结、参考文献与勘误 |
| `history/` | 10 月 22 日 GA/ACO/PSO 组合与 10 月 24 日各轮研究包、统计与负例 |
| `verification/` | 核验脚本 `verify.py`；全包指纹位于根目录 `MANIFEST.sha256.json` |

## 规则与目标口径

主运行脚本已内置选中窗口，无需联网或解压完整 40MB 数据；如需还原原始字节，请先运行 `uv run python research/recommended-20261024/data/unpack.py`（见 [data/README.md](data/README.md)）。业务规则为入库与出库自然部分重叠、一单一单位运输、批次之间安全待命，全部流关闭且任务完成后最终返库。

独立线性目标为 $F = 0.5\,T/900 + 0.3\,R/900 + 0.2\,D/5400$（越低越好）：**T** 为最后一单完成时刻（不含最终返库），**R** 为平均发布到完成耗时，**D** 为含最终返库的实际总里程（格数）；辅助保留空驶、P90、等待与 CPU。

## 实验范围与许可说明

- `gate` 是在当前固定业务规则与搜索预算下经多轮配对对比选定的启发式在线调度方案；目标权重（0.5/0.3/0.2）为课程实验统一设定，跨方案比较均在同一协议与目标口径下开展。
- 真实订单流映射至 62×47 课程仿真网格（货位映射种子 17），货架层数、装卸耗时与运动速率按统一仿真参数建模。
- 数据来源与许可见 `data/raw/LICENSE`、根目录 [NOTICE.md](../../NOTICE.md) 及 [参考文献与借鉴边界](docs/参考文献与借鉴边界.md)。
