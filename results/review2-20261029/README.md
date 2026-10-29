# 第二轮审核证据

- [技术报告](../../docs/experiments/review2-20261029.md)：日期口径、CPU瓶颈、采用决定、模型限制和复现命令。
- [verification.json](verification.json)：435项全套测试、3项新增延迟工具测试、580历史回放、24次WEPA回放和独立安装验证。
- [development-runs.json](development-runs.json) / [development-summary.json](development-summary.json)：33次完整开发运行、日期统计及原筛选子集。
- [selection-before-validation.json](selection-before-validation.json)：提交9c2b21a中的开发选型，先于验证启动。
- [validation-runs.json](validation-runs.json) / [validation-summary.json](validation-summary.json)：45次验证运行、10个日期的bootstrap与符号检验。
- [adoption.json](adoption.json)：三项默认采用门槛均未达到，gate保持默认。
- [measured-latency-plan.json](measured-latency-plan.json) / [measured-latency-runs.json](measured-latency-runs.json) / [measured-latency-summary.json](measured-latency-summary.json)：测量前固定的单机串行计划、60次补充运行、重新验解与日期等权对照；不用于选型。
- [paired-cpu-summary.json](paired-cpu-summary.json) / [cpu-profile-summary.json](cpu-profile-summary.json)：两窗四对无剖析计时、完整语义哈希及热点分解；合计CPU下降19.81%，并行负载与单次重复限制已保留。
- [anchor-regressions.json](anchor-regressions.json)：原5个退化窗口10次轨迹重新验解、首次分叉和随后3次搜索；截图见[逐窗报告](../../docs/experiments/anchor-regressions.md)。
- [historical-golden.json](historical-golden.json) / [wepa-golden.json](wepa-golden.json)：旧580例与原WEPA12种组合双重复的紧凑证据。

新日期协议唯一权威输入位于 `protocols/wepa-20261029-dates.json`，源码提交6daa04c、协议提交f6cd41e。全轨迹只在本地ignored runs，公开行保留原文件SHA256；重新验解需按冻结源码复现轨迹，不能仅凭紧凑行运行验解器。旧8窗与新7窗封存集合算法运行数均为0。补充延迟的none/measured身份分开核验后才按相同输入配对，没有把不同协议或计时当成同一测量。
