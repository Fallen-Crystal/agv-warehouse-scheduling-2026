# Simplified Dispatch and Controlled Routing Study Plan

This study implements a simplified soft-region single-GA dispatcher and evaluates three routing backends under identical warehouse rules: SIPP, time-space A\*, and ACO-guided spatial A\* with SIPP timing.

## Experimental Design

- **Environment & Rules**: Large 62×47 layout, 6 homogeneous AGVs, 5 rack levels, real WEPAStacks arrival streams, with physical inventory, rack-layer precedence, terminal access, bay locking, safe standby, and final depot return unchanged.
- **Objective**: `F = 0.5*T/T_ref + 0.3*R/R_ref + 0.2*D/D_ref` (lower is better), using `FCFS + SIPP` as the shared per-scenario reference denominator across all dispatchers and routing backends.
- **Dispatch Development (Days 12, 32, 33, 45; `seed = 0`)**: Compare `adaptive_ga`, `simple_ga`, `soft_ga`, `eta`, and `fcfs` on SIPP. Select the best valid simplified GA variant by mean development `F` (breaking ties by CPU time).
- **Simplified GA Architecture**: Joint permutation + vehicle-ownership encoding initialized with a nearest-ETA feasible seed, without separate pre-GA batch matching or post-GA repair. Budget: population 12, 8 generations, up to 96 distinct proxy evaluations, 3 complete rollouts, and 512 low-level routing queries per rollout.
- **Soft-Region Guidance (`soft_ga`)**: Divides shelves into upper/lower regions around the equipment zone; 75% of vehicle-owner proposals draw from local and earliest-available vehicles while 25% draw globally, allowing cross-region collaboration.
- **Triggering**: Same-timestamp arrivals are published together; re-search triggers on new visible work, observed stream close, or task completions separated by at least 64 steps.
- **Routing Development (Days 12, 32, 33, 45; `seed = 0`)**: Evaluate `sipp`, `astar`, and `aco` (at most 2 corridor timing candidates per leg) with the selected dispatcher.
- **Validation (Days 62, 66, 69)**: Earliest qualifying 900-second windows after day 61 (35–65 requests, 2–5 SKUs, initial stock ≤ 900, ≥ 5 inbound and ≥ 5 outbound). Advanced methods run `seed = 0, 1` (averaged per day before cross-day averaging).
- **Resource Limits & System Scope**: 180s CPU limit and 600s wall limit per single-worker run. Routing comparisons run closed-loop (routing feedback influences subsequent online dispatching).

## Verification Scope

Observed execution and verification results are recorded in [实验报告.md](实验报告.md) and the archive artifacts (`results/audit.json`, `results/tests-final.log`, `results/clean-replay.json`):

- Backend-aware detached snapshots and rollouts ensuring A\* and ACO predictions use their selected routing backend.
- Joint GA and soft-region operators preserving full global vehicle reachability and unchanged physical constraints.
- Frozen source/protocol hashing before development, paired development/routing/validation runs, and independent trajectory verification.
- Complete reporting of `F`, `T`, `R`, `D`, empty travel distance, `P90`, CPU/wall time, and per-day paired comparisons.
