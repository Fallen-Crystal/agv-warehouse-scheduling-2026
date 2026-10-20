"""Train a candidate ranker on MovingAI-derived, split-by-region MAPD scenes."""

import hashlib
import statistics
from pathlib import Path

from agv.evaluation.validation import validate
from agv.io.movingai import REGIONS, derived_scene, map_provenance
from agv.io.scenes import scenario_id
from agv.io.storage import write_json
from agv.learning.ranker import fit
from agv.runner.compat import run_optimized as run

TRAIN_SEEDS = tuple(range(8))
VALIDATION_SEEDS = tuple(range(100, 103))
TEST_SEEDS = tuple(range(200, 206))


def train(map_path, output):
    provenance = map_provenance(map_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    partitions = {}
    scene_records = []
    for split, seeds in [("train", TRAIN_SEEDS), ("validation", VALIDATION_SEEDS)]:
        rows = []
        for seed in seeds:
            scenario = derived_scene(map_path, split, seed, task_count=16)
            samples = []
            result = run(
                scenario,
                assignment="greedy",
                router_kind="sipp",
                neighborhoods="conflict",
                collect=samples,
            )
            validate(scenario, result)
            digest = scenario_id(scenario)
            for sample in samples:
                sample.update(split=split, seed=seed, scenario_sha256=digest)
                sample["target"] = max(-5, min(10, sample["target"]))
            rows.extend(samples)
            scene_records.append(
                dict(
                    split=split,
                    seed=seed,
                    scenario_sha256=digest,
                    feasible=result["feasible"],
                    samples=len(samples),
                )
            )
            print("Training data", split, seed, len(samples), flush=True)
        partitions[split] = rows
        write_json(output / (split + "-samples.json"), rows)
    candidates = []
    for penalty in (0.01, 0.1, 1.0):
        model = fit(partitions["train"], regularization=penalty, steps=500)
        mse = statistics.mean(
            (model.predict(s["features"]) - s["target"]) ** 2 for s in partitions["validation"]
        )
        candidates.append((mse, penalty, model))
    mse, penalty, model = min(candidates, key=lambda row: row[:2])
    write_json(output / "candidate-ranker.json", model.to_dict())
    write_json(
        output / "training-report.json",
        dict(
            source_url=provenance["source_url"],
            license=provenance["license"],
            origin=provenance["origin"],
            source_map_sha256=hashlib.sha256(Path(map_path).read_bytes()).hexdigest(),
            regions=REGIONS,
            train_seeds=TRAIN_SEEDS,
            validation_seeds=VALIDATION_SEEDS,
            heldout_test_seeds=TEST_SEEDS,
            samples={k: len(v) for k, v in partitions.items()},
            scenes=scene_records,
            selected_regularization=penalty,
            validation_mse=mse,
            validation_constant_mse=statistics.mean(
                (model.intercept - s["target"]) ** 2 for s in partitions["validation"]
            ),
            target="clipped primary remaining-flow gain of a candidate; infeasible=-1, range[-5,10]",
            scope="MovingAI geometry-derived MAPD, disjoint regions/seeds of ONE warehouse; not official MAPF scores",
        ),
    )
    return model
