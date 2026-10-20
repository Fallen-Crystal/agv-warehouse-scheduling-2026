# 架构重构验证证据

基线为 main@81dc593；[verification.json](verification.json) 汇总本机299项测试、96组几何/24组执行矩阵、独立wheel和静态检查。完整源码冻结与580次逐字段回放见 [golden证据](../../tests/golden/full-replay.json)，重构范围及限制见 [验收记录](../../docs/architecture-refactor.md)。CPU倍率是同一场景集合的逐局中位数比较，不表示算法F改善。
