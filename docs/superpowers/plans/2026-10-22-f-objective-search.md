# Fixed-F scheduling experiment

The user authorizes testing alternative dispatch algorithms, accepting increases in
individual metrics when the original total F improves. T, R and D are outputs;
their proposal-search emphasis may vary, but final weights and denominators do not.

## Fixed contracts

F=.5T/Tref+.3R/Rref+.2D/Dref, E=.05D. Same-scene official references;
four-neighbor V9.1, homogeneous cars, published orders only, per-face layer and
pickup locks, delivery-only stations, between-batch standby, final home return.
Keep v1 modules and public defaults unchanged in an isolated copy.

## Implementation

1. Add focused tests for exact small-batch matching, proposal-weight masking with
   invariant final weights, hidden-future invariance and independently valid runs.
2. Add a calibrated visible-work proxy and a finite-budget permutation search
   (GA, equal-budget random, and GA plus relocate/swap local search).
3. Add a pure priority driver with interchangeable greedy or exact min-cost batch
   matching. Bind only currently dispatchable jobs through the existing gateway.
4. Add an optional runner reusing the sole execution loop and actual SIPP router.
5. Profile v1 once to distinguish computational overhead from assignment quality.

## Experiment design

Development: medium/large, static/dynamic, 4 cars, 12/8 orders, 8 layers,
seeds4100..4102. Frozen source per run. Compare greedy, v1 GA, matching only,
random/matching, and new GA/matching proposal objectives T,R,D,TR,TD,RD,TRD.
Add hybrid local search as a separate candidate. Proposal weights may be masked;
the true visible-rollout acceptance and final evaluator always use all three terms.
Use a common deterministic proxy-evaluation cap and three real rollout candidates.

Select at most two predeclared best nonredundant candidates by development mean F,
with no R/P90 monotonic guard. Then freeze source/configurations before new tests.
Final: four maps x static/dynamic x six new seeds6100..6105, 4 cars, 12/8 orders,
original greedy and v1 GA controls plus selected candidates. Rotate execution order.
Report valid/failed runs, F,T,R,D, signed component contributions, CPU and regressions;
cluster intervals by environment seed. No selecting per-case best after the fact.

If no development candidate improves, try a second focused hypothesis before the
formal freeze; retain all failures and comparisons. Do not claim improvement if absent.
Small single-car exact DP and multi-car upper/lower certificates quantify optimum
gaps only in supported static subclasses. No general online global-optimum claim.

## Completion

Target: verified F decrease versus v1 (practical aim >=1% mean with positive paired
bootstrap lower endpoint), or exact optimality on certified small cases. Report
the actual outcome and limits. Deliver runnable code, fixed protocol, raw results,
negative cases, tests and mathematical delta-F attribution. No weight changes.

## Steering and formal freeze (2026-10-22)

The user additionally asks whether R and D can be combined and requests literature
support for variables/weights. Added a primary-source review and offline rescoring
of old feasible traces. These are explicitly separate from new-weight optimization;
no objective code, weights, normalization or service constraints were changed.

Development completed: all 168 executions valid, all 12 scenes included (a live
9-scene interim analysis was overwritten with the completed 12-scene analysis).
Choose ga_RD and ga_TR by the declared mean-F ranking among non-control candidates:
RD +1.6437%, TR +1.0974% versus v1 on development; RD uncertainty includes zero.
Use both across all four maps and both modes, seeds6100..6105, optimizer seeds0/1/2.
Do not choose per scene, and retain all development failures/negative comparisons.
The choice only changes candidate proposal emphasis; acceptance and final scoring
always retain the original three-term coefficients. No R/P90 protection is imposed.

## Second hypothesis after the first holdout failed to confirm improvement

First holdout: 384/384 valid, RD -0.5237% vs v1; TR +0.2712% with interval spanning
zero. Retain these negative results. Do not promote either isolated mask.
New mechanism: retain the three v1 proposals as an anchor and add diverse TR/RD
batch-matching proposals; compare all with one shared full-F visible rollout score.
This portfolio spends more compute (up to nine candidate rollouts), so report its
cost explicitly rather than claim same-budget algorithmic superiority.
Fresh development: seeds5100..5102, medium/large x static/dynamic, greedy/v1/portfolio.
Fresh confirmation if worthwhile: seeds7100..7105, all four maps x both modes,
greedy/v1 once and portfolio optimizer seeds0/1/2 (240 runs). No selecting a winner
per scene or selecting the best optimizer seed. Keep original F and hard rules.
