# 历史研究身份

2026-10-24交付包与原始数据保留在 `research/recommended-20261024/`。源文件和历史实验身份不重签，普通源码从2026-10-29起位于 `src/agv/`。

| 发布物 | 原始位置 | SHA256 |
|---|---|---|
| 可移植推荐运行包 | research/recommended-20261024/current/runtime.zip | 3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b |
| 原始请求gzip | research/recommended-20261024/data/raw/2_orders.json.gz | afa093e9b62ada0a4344b91387b61448893dd3417282b579169278e0eba0b3e2 |

其他历史包的身份见原 `history/index.json` 与 `MANIFEST.sha256.json`。code-guide副本已删除，其原字节仍可从runtime.zip恢复（其中三个展示文件当时仅规范化了CRLF）。四个已迁移README／launcher／verifier不再由旧清单证明当前身份；新的代码走源码指纹、金标准和CI。`verification/verify.py`明确报告这些边界，仍检查其他89个发布文件与11个历史guide字节。

没有重写Git历史、强制推送或声称删除当前树ZIP就能缩小历史clone。压缩请求约1.09MB、运行包约1.27MB，先保留可离线复现；历史ZIP迁到Release属于后续独立归档工作，不能在验证下载哈希前丢弃唯一副本。
