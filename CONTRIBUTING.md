# Development

Python 3.10+; runtime uses only the standard library.

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -t . -v
ruff check src tests
ruff format --check src tests
python -m build --wheel
```

Add a named configuration in `src/agv/registry.py` when comparing a solver. Preserve the online observation boundary: policies may read released orders, assigned jobs and known reservations; they may not read unreleased scenario tasks. Plan changes must preserve task ownership, all executed positions and service intervals already begun. Keep full collision and service validation; learning may rank search candidates but may never authorize movement.

Use `tests/unit` for domain/planner/serialization contracts and `tests/integration` for installed CLI/HTTP boundaries. A new router should be checked against the time-expanded oracle for feasibility and earliest finish, including reverse edges, service duration and horizon endpoints. Tests must run without network, public downloads or system proxy assumptions.

Store generated full outputs under ignored `runs/`. Commit compact summaries and deliberately selected traces to `results/`; don't commit caches, virtual environments or repeated handoff folders. Formal benchmarks freeze source hashes: do not edit `src/agv` during a run. Keep failures in success-rate/completion-rate reporting, and compare full-task times on paired successful instances only.

For trained changes, keep training, validation and heldout source regions/seeds separate. Record source attribution/hash, model schema, features, fit/selection settings and negative results. Changing the model requires renewed heldout evaluation.

## Integrated WEPA changes

The ordinary package source is authoritative; do not edit or re-sign `runtime.zip`.
Use `src/agv/registry.py` for typed compositions; the 23 historical solver names
retain their original order, while WEPA has a separate explicit model registry.
Algorithm PRs include a frozen protocol, independent validation, F/T/R/D/P90,
empty moves, CPU, per-window regressions and paired uncertainty. Windows are
independent units; random seeds are repeated measurements, not extra windows.
A refactor PR includes both the historical 580-case replay and the WEPA full
trajectory hashes. Never replace expected hashes using refactored output.
Keep sealed windows unopened. Select on development before validation starts;
retain failed or timed-out runs and disqualify methods with invalid runs.
Different objective_id values must never be pooled. A measured-latency result
also needs its machine identity/calibration and is not a deterministic golden.
