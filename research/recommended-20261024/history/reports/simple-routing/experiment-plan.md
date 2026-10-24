# Simplified dispatch and controlled routing study

Human authorization: implement the simplified soft-region/single-GA dispatcher, then compare SIPP, time-space A*, and ACO-guided spatial A* with SIPP timing. No new approval is needed for this authorized local study. Original studies/packages remain immutable.

## Frozen design before results

- Same source requests and reviewed geometry, large/6 cars/5 levels, physical stock/layer/terminal/bay-lock/standby/final-return rules unchanged.
- Same official F=.5T/Tref+.3R/Rref+.2D/Dref. FCFS+SIPP is the shared reference across routing backends, never recompute a different denominator per backend.
- Dispatch development: days12/32/33/45, seeds0. Compare old adaptive_ga, simple_ga, soft_ga, eta, fcfs on SIPP. Select the best valid simplified GA method by mean development F, CPU breaks ties. Retain old method even if simplification loses.
- Simplified GA has sequence and vehicle ownership genes. No independent batch-matching optimizer, ACO/PSO dispatch, or post-GA repair. Near-neighbor seed is only initialization. Fixed 12 population,8 generations,96 distinct proxy evaluations,3 complete previews,512 low-level query counts per preview. Retain feasible baseline/old plan if no improvement.
- soft_ga: two equipment-separated shelf regions organize candidate car pools. Use local and nearest estimated-finish vehicles for 75% of owner proposals and keep 25% global proposals; no cross-region ban and no permanently dedicated fleet.
- Same-timestamp arrivals are published together. Search on new visible work, observed close, or relevant completion changes separated by64 steps. Idle ticks do not cause repeated GA search.
- Routing development: same four cases, selected dispatcher, seed0; backends sipp/astar/aco. Select best valid mean development F, CPU tie-break. ACO implementation reused from uploaded source, at most2 corridor timing candidates per leg; temporal safety always enforced.
- Untouched validation: earliest qualifying days after61 with900sec windows,35..65 requests,2..5 SKUs,initial stock<=900,both directions>=5. Select62/66/69 based on inputs only. Do not inspect their algorithm results before selection/freeze.
- Validation compares both simplified methods, old adaptive_ga, eta,fcfs on SIPP, plus the chosen simplified dispatch on astar and aco. Advanced methods use seeds0/1. All use the same cases and reference; repeated seeds are not independent days.
- CPU guard180s, wall guard600s per process, single worker to limit desktop contention. Longer wall guard than prior study is declared in advance; record CPU and wall separately, failures stay in primary tables. No retries selected for quality.
- The routing comparison holds dispatcher implementation/parameters/seeds fixed but is closed-loop: routing feedback may change later assignments. It is an end-to-end backend comparison, not fixed-task-route-only causality.

## Implementation and verification

The unchecked list below preserves the pre-run plan, not current completion status. Observed completion is recorded in the experiment report, `results/audit.json`, `results/tests-final.log`, and `results/clean-replay.json`; delivery checks are recorded by `package_study.py` in the external package receipt.

- [ ] Backend-aware detached snapshots and complete rollouts. Test that A* and ACO predictions do not silently use SIPP-only execution.
- [ ] Joint GA and soft-region initialization/mutation; all global owners remain reachable. No physical model edit.
- [ ] Reuse physical executor, independent checker and source-provenance manifests.
- [ ] Freeze source/protocol before development; retain attempted pilot output. Select before validation.
- [ ] Complete paired development, routing development and untouched validation; independently recheck all successful trajectories and source mapping.
- [ ] Report F,T,R,D,empty distance,P90,CPU,wall,failures and paired per-day effects. No global-optimality or universal speedup claim.
- [ ] Clean-directory CLI replay and checksum-verified portable delivery.
