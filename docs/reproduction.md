# Reproduction and output policy

## Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
agv serve
agv run --input examples/scenarios/dynamic_medium_burst.json --algorithm sipp_budget --output runs/demo.json
```

On Windows activate `.venv\Scripts\activate`; the installed `agv` command is the same. The core has no third-party runtime dependencies and needs no training framework. `python -m agv` is equivalent to `agv`, so current working directory need not be the source directory.

The viewer server binds127.0.0.1 only and reads installed assets; it does not write generated HTML next to package source. Select an algorithm before generating a new scene. To replay a chosen raw result, use the scene import control; saved JSON carries the chosen algorithm.

## Data

One small attributed public map is included. Download another byte-identical copy into a fresh destination if needed:

```bash
agv fetch-data --output runs/downloaded/warehouse-10-20-10-2-1.map
```

`data/NOTICE.md` and the adjacent source JSON document the official source, license and hash. Training/benchmark use the configured non-overlapping crop profiles, not the official `.scen` endpoint-pair workload. No private dataset is required or bundled.

## Experiments and training

```bash
agv benchmark --seeds 10 --map data/maps/warehouse-10-20-10-2-1.map --output runs/reproduction
agv train --map data/maps/warehouse-10-20-10-2-1.map --output runs/training
```

Both output directories must be new. Each experiment row includes solver, seed, actual scene SHA256, runtime, completed count, feasibility, state-expansion counters and flow/distance metrics. All results, including failed instances, undergo independent path/service/metric validation. Summary cost comparisons include only paired complete successes; pressure failures are retained separately.

`manifest.json` has `status=running` until all rows finish. Completed runs record all relevant code/model/asset hashes. Editing those sources during a benchmark invalidates the run. The published measurement snapshot is Git commit `29d86e7`; later parser/provenance/default-CLI hardening does not change the solvers/model. Run `python scripts/verify_results.py` from a full Git checkout to audit the frozen source and all current scene hashes against the measurements. Timing excludes interpreter import startup and post-run independent validation but includes simulation, dispatch, planning and in-loop atomic route audits. One timing measurement per seed is a practical descriptor, not a tight speed confidence interval. The isolated routing benchmark uses five repeats per case, with a median.

Training samples and all generated files remain under ignored `runs/`; curated statistics and selected traces are copied to `results/`. This keeps the public tree navigable and avoids committing the same map/task/trajectory repeatedly. Historical v1 source/outputs remain accessible at commit `d79aa07`.
