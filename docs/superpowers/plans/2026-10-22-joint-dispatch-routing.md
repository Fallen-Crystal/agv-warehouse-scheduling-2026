# Joint dispatch and routing experiment implementation plan

Goal: improve fixed F relative to the previous portfolio and make dispatch/routing
feedback explicit, without relaxing warehouse rules or changing existing defaults.
The user explicitly authorizes the next experiment and interface work.

Architecture: keep one runner and one atomic command gateway. Add an observation-
only routing oracle, stamped proposals and an optional post-assignment callback.
Search only unassigned visible orders; committed tasks and executed prefixes stay.
Python standard library; actual SIPP previews and independent original validation.

## Fixed model and evidence

F=.5T/Tref+.3R/Rref+.2D/Dref, E=.05D display only; official same-scene references.
No hidden orders/end-of-stream, collision/service/shelf/station rules unchanged.
Policies use visible-work proxy scales; this is not full online global optimality.
Original 107 source files and all prior results remain in the previous directory.

## Implementation units

1. policy/routing_contract.py: RoutingOracle evaluates a stateless driver through
   ShadowState; RouteFeedback carries completion, failure reason, T/R/D, accepted
   records, real route calls/expansions and a visible-snapshot fingerprint.
   DispatchProposal rejects stale snapshots. No environment-private field access.
2. planning/joint_orders.py: fixed-owner visible schedule proxy and bounded unique
   relocation/swap/sequence neighbors. It never binds busy vehicles to new jobs.
3. policy/joint_orders.py: portfolio anchor, explicit future-order ownership,
   true-SIPP evaluation of bounded neighbors, optional reservation-order variants;
   failed/incomplete previews cannot win; retain incumbent and actual feedback.
4. runner/run.py: backwards-compatible optional on_assignment callback after real
   assignment; tests verify fresh post-commit observation and partial rejection.
   runner/joint_research.py composes the optional mode through this same runner.

Focused tests precede implementation: stale snapshots, detached feedback, hidden-
future invariance, owner legality, budget exhaustion/fallback, partial rejection,
batch priority affects reservations but not ownership, independent valid traces.

## Experiments frozen before collection

Development: medium/large x static/dynamic x seeds8100..8102, 4 cars, 8 levels,
12/8 orders. Baseline portfolio; assignment LNS; reservation-priority only; both;
same-budget random-neighbor control; add user-requested ACO and random-key PSO
with joint sequence/vehicle encoding (seven variants, 84 development executions).
ACO uses 12 ants, evaporation .2, up to 32 rounds; PSO uses 12 particles,
inertia .7 and acceleration 1.4/1.4, up to 32 rounds. Both stop after 192 unique
proxy evaluations and return at most eight real SIPP candidates. These are adapted
baseline implementations, not reproductions of published warehouse solvers.
Upper bounds on actual previews and counted
route calls are recorded, along with CPU, F,T,R,D, regression and invalid runs.
Select at most one candidate based on mean paired F versus portfolio; no R guard.

Confirmation: four maps x both modes x seeds18100..18105 (48 new scenes), seed0
for both baseline and selected candidate (96 executions). A separate robustness
panel uses seeds19100/19101, all maps/modes, optimizer seeds1/2 (64 executions).
Do not pool robustness into the primary endpoint or select best repeats per case.
Primary paired confidence intervals cluster by six environment seeds.

Small exact cases and 10-car/single-D stress plus interface counterexamples guard
feasibility. Compare equal-budget random neighborhoods before attributing gains
to informed LNS. If no useful development improvement, try one focused variant on
development; preserve all failures and do not announce gains absent evidence.

Run relevant tests, architecture, formatting, then full standard tests with UTF-8,
workspace temporary directory and normal permissions for Windows atomic hard links.
Freeze sources during every matrix. Save source snapshots when changing versions.
Deliver full code, contract documentation, traces, CSV, limitations and audit hashes.
No GitHub push or default strategy change is included in this request.
