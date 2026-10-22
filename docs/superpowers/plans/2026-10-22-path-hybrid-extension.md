# User-steered extension: actual route hybrids and regime-specific combinations

The user clarified during the joint-order development matrix that ACO/PSO should
also operate on path planning, including A* hybrids, and static/dynamic solver
combinations may differ. Preserve the completed original matrix, no replacement
of negative results. No original confirmation scenarios have been inspected.

Keep F=.5 normalized T+.3 normalized R+.2 normalized D, all physical rules and
official reference denominators unchanged. Add an injectable router at the
composition root, identical for real execution and visible-only shadow worlds.
The production default remains untouched. Keep the single execution loop.

Path methods: SIPP, time-space A*, ACO-guided spatial A*+SIPP timing,
PSO cost-field spatial A*+SIPP timing, and the two hybrids with time-space A*
timing instead. Every corridor is decoded under actual vertex/reverse-edge,
service, own-home and delivery-station constraints. Retain the original route on
failure. Four new timed corridors per leg at most; 12 spatial proposals at most.
ACO evaporation .2; PSO 4 particles, 3 rounds, inertia .7, c1=c2=1.4. Routing uses
geometry/committed reservations only; no future orders or scoring denominators.
Spatial proposals are constructed with positive A* edge-cost fields. Local
selection is duration ratio+.4 movement ratio+.02 reservation proximity; bounded
extra duration <= min(4,ceil(.1*original duration)). This local heuristic is NOT
the official F and does not guarantee an improvement to the full simulation.
Measure that improvement or regression in paired whole-scene executions.

The original 84-run development matrix is source-frozen in the sibling joint
study folder. Aggregate best was assignment LNS (ties combined, lower compute).
Static best was assignment; dynamic best was ACO order search. Path development
will compare six routers x portfolio/assignment orders, plus ACO orders only in
dynamic cases, on the same development family, medium/large x two modes x
seeds8100..8102, 12/8 jobs, 4 cars. This is 180 executions. All additional
computational work is counted; no claim of equal compute to the original solver.
If a route hybrid is prohibitively costly in pilot, record all pilot results and
use a smaller explicitly frozen screening panel before the main confirmation.

Choose one combination separately per regime using development F only; report
the benefit over both original portfolio+SIPP and assignment+SIPP. Confirm on
four maps x two modes x seeds18100..18105, optimizer seed0; 48 new scenes, no
selection from holdout outcomes. Add optimizer-seed robustness on disjoint
seeds19100/19101 when a stochastic hybrid wins. Never select best seed per case.
If a new combination fails confirmation, keep the previous method as default
and report the failure. The study may conclude there is no useful path gain.

Verify safety on random reservation patterns, nontrivial route changes,
whole-warehouse validity, hidden-future invariance, and unchanged default traces.
Final package retains both source snapshots, all matrices, and exact small-case
checks. No remote upload or merge is part of this request.

Pilot amendment before development: the all-leg version was interrupted for compute cost; partial traces and source snapshot retained. The frozen development version searches only when the base route duration exceeds static distance plus service. This congestion trigger reduces work but may miss anticipatory equal-cost route changes. No confirmation data informed this change.

Pre-confirmation adoption gate: keep the frozen static/dynamic development profile for confirmation. Recommend a split profile only if its whole-panel F gain is supported and the dynamic addition is better than assignment+SIPP; otherwise prefer the pre-specified unified assignment+SIPP alternative if confirmed, or retain portfolio+SIPP. No best-per-case or best-seed selection. Add a diagnostic matched-arrival panel with identical eight-job sets, four maps x seeds8150/8151 x static/dynamic, to avoid confounding arrival regime with order count. This panel cannot trigger a new search or parameter retuning.

Before reading confirmation F outcomes, add the dynamic component-removal comparator aco__sipp on the same 24 confirmation scenes, optimizer seed0. It isolates adding route hybrid search to the same dispatch architecture. If dispatch improvement is supported but the path addition is not, prefer the pre-specified simplified ACO-dispatch+SIPP alternative over unsupported path complexity. Report all comparisons and their finite-sample limits; no per-case switching.
