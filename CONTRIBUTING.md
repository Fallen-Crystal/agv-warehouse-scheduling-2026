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

Add a named configuration in `src/agv/dispatch/registry.py` when comparing a solver. Preserve the online observation boundary: policies may read released orders, assigned jobs and known reservations; they may not read unreleased scenario tasks. Plan changes must preserve task ownership, all executed positions and service intervals already begun. Keep full collision and service validation; learning may rank search candidates but may never authorize movement.

Use `tests/unit` for domain/planner/serialization contracts and `tests/integration` for installed CLI/HTTP boundaries. A new router should be checked against the time-expanded oracle for feasibility and earliest finish, including reverse edges, service duration and horizon endpoints. Tests must run without network, public downloads or system proxy assumptions.

Store generated full outputs under ignored `runs/`. Commit compact summaries and deliberately selected traces to `results/`; don't commit caches, virtual environments or repeated handoff folders. Formal benchmarks freeze source hashes: do not edit `src/agv` during a run. Keep failures in success-rate/completion-rate reporting, and compare full-task times on paired successful instances only.

For trained changes, keep training, validation and heldout source regions/seeds separate. Record source attribution/hash, model schema, features, fit/selection settings and negative results. Changing the model requires renewed heldout evaluation.
