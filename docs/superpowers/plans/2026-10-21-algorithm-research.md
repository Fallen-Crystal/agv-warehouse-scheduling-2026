# AGV algorithm research implementation plan

**Goal:** Establish an exact small static reference, then improve online dispatch and coordinated routing without changing V9.1 rules or the fixed 50/30/20 objective.

**Authorization:** The user explicitly approved the previously proposed sequence and autonomous repeated experiments on 2026-10-21. Work on this isolated copy of cd8d1be; do not merge the teammate's PR or change default algorithms.

**Architecture:** New optional research modules consume public observations and existing command/validation APIs. Exact references are explicitly offline and reject unsupported cases. All final results pass the unmodified independent validator and production scorer.

**Literature:** Ropke/Pisinger 2006 ALNS (10.1287/trsc.1050.0135); Li et al. 2021 MAPF-LNS (10.24963/ijcai.2021/568); Li/Ruml/Koenig 2021 EECBS (10.1609/aaai.v35i14.17466). Adapt ideas, do not inherit unproved guarantees.

## Protocol

- Development seeds 60-63; freeze source and configuration before new holdout seeds 1000-1011.
- Include static backlog, dynamic uniform, shared bursts; four canonical maps, initially 4 vehicles/12 orders, plus 1 vehicle/8 orders exact references and 10 vehicle/8 level stress.
- Keep all failures. Compare paired F, T, mean flow, D, P90, CPU and success. Bootstrap by scene; report strata and regression counts. Do not pool exploratory and holdout samples.
- Optimization-loop numeric metric: mean development F ratio against sipp_stream_dispatch; baseline 1, target <=0.98. Guard: independent trajectory validation on every run plus contract tests. Failed source trials reverted, raw evidence retained outside repository.
- Satisfactory scientific result: exact zero-gap certificates on supported small cases, or positive paired holdout improvement interval with no validity regressions. Never call baseline improvement an optimality gap.

## Tasks

- [ ] Build single-vehicle static exact dynamic programming reference, prove its scope and compare with independent exhaustive permutations.
- [ ] Add reproducible paired benchmark and read-only scalar development measurement.
- [ ] Run controlled order-search trials, retaining only measurable gains.
- [ ] Test reservation-priority and multi-vehicle suffix coordination separately; freeze service and ownership and validate complete suffixes.
- [ ] Freeze chosen code/config, execute holdout and boundary stress, run regression tests and publish a concise report with retained and rejected trials.

No extra approval is needed for the already authorized local experiments. Publishing or merging is separate from this task's local research deliverable.
