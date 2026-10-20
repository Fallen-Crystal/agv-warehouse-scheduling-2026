# Pre-refactor trajectory baseline

`manifest.json` and `results.json.gz` are recorded from commit
`cabc2120c15d5810823bdc1ea84b0a18eb846065`, before architecture changes.
The source was exported with `git archive HEAD` into
`tmp/architecture-baseline/`; the recorder starts a separate interpreter with
that archive's `src/` on `PYTHONPATH`. It refuses to record directly from the
working source tree or replace an existing baseline without `--overwrite`.
Do not regenerate expected results to make a refactor pass.

The baseline covers all 23 registered solver names and seeds 10–19:

| Profile | Solvers | Seeds | Runs |
| --- | ---: | ---: | ---: |
| Legacy, dynamic 4 jobs / 2 vehicles | 13 | 10 | 130 |
| V4, dynamic 4 jobs / 2 vehicles | 13 | 10 | 130 |
| V9, dynamic 4 jobs / 2 vehicles | 16 | 10 | 160 |
| V9.1, dynamic 4 jobs / 2 vehicles | 8 | 10 | 80 |
| V9.1, static 12 jobs / 4 vehicles | 8 | 10 | 80 |
| Total | | | 580 |

Historical finite standby solvers require V9; stream solvers require V9.1.
These are explicit business-profile boundaries, not omitted failed cases.
Every recorded or replayed result must pass the independent validator.
Exceptions are retained and fail the command. All expected results are feasible.

The compressed snapshot contains the original serialized scenes and complete
normalized results, including paths, assignments, interval states, metrics,
scores, algorithm metadata, decisions and diagnostics. Only measured real-clock
keys `wall_seconds`, `cpu_seconds`, and `decision_cpu_seconds` are excluded
recursively. Simulated times, ordering, floats and routing counters are retained.
The manifest includes SHA-256 hashes for the payload and for each normalized
result, path collection and assignment collection, plus original execution times.

Recording completed with 580/580 feasible, independently validated results and
zero exceptions in 628.114 measured wall seconds. Per-run CPU medians were:

| Profile | Baseline CPU median (seconds) |
| --- | ---: |
| Legacy | 0.044893 |
| V4 | 0.175341 |
| V9 | 1.926891 |
| V9.1, 4 jobs / 2 vehicles | 1.326580 |
| V9.1, 12 jobs / 4 vehicles | 1.565342 |

Per-run timing covers `run_named`, including its existing score computation;
the recorder's additional independent validation is outside that timer. Total
recording wall time includes validation. BCRD actually searched candidates in
8 of the 10 dense V9.1 seeds; the other two retain the declared queue gate.

Run the full architecture gate from the repository root:

```sh
.venv/bin/python tests/golden/record.py replay
```

This replays all 580 cases against current `src/`, checks byte-identical canonical
JSON and writes ignored `tests/golden/last-replay.json` with per-run timings and
the exact differing fields. The report records SHA-256 hashes for every source
and asset file before and after replay; a source change during replay fails the
command. Preserve a separate full-run evidence file with:

```sh
.venv/bin/python tests/golden/record.py replay --report tests/golden/full-replay.json
```

This output is not overwritten by ordinary replay or unittest. To validate the
recorder against its own archive:

```sh
.venv/bin/python tests/golden/record.py replay --source-root tmp/architecture-baseline
```

Normal unittest discovery replays seed 10: 58 runs covering every solver/profile.
Set `AGV_GOLDEN_FULL=1` to run all 580 cases through unittest as well:

```sh
AGV_GOLDEN_FULL=1 .venv/bin/python -m unittest tests.golden.test_replay
```

This is a deterministic refactoring regression gate, not an algorithm-quality
benchmark or a hardware-controlled speed experiment. The 12-job V9.1 scenes are
included to exercise budgeted rollouts and provide comparable baseline timing.
