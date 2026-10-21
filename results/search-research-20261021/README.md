# 2026-10-21 算法研究证据

本分支基于cd8d1be，新增排列GA、单车精确DP和双车小例最优证书。没有合并到main，也未改写同学架构分支。

rows.jsonl和runs.csv保留全部208次执行；freeze.json保存最终源码及72场景协议。tests.log记录本地完整352项测试通过，mechanical-verification.json记录全部208条轨迹的重新验解，不表示远程CI或外部审查已通过。

按CONTRIBUTING，只提交精选完整轨迹归档selected-evidence.tar.gz；selection-manifest.json列出选择标准及SHA256。完整208条原始轨迹保留在本地完整代码包，可用实验脚本重新生成。interrupted-phase保留前一轮因耗时中断的178条记录，不与最终留出混合。

代码运行和结果解释见[算法说明](../../算法实验_README.md)；方法和文献见[研究说明](../../docs/order-search-research.md)。
