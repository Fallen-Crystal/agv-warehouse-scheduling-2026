"""Audit compact published evidence and its frozen measurement Git snapshot."""

import csv
import hashlib
import json
import subprocess
from pathlib import Path

from agv.domain import example
from agv.evaluation.validation import validate
from agv.experiments.benchmark import CONFIGS
from agv.io.movingai import derived_scene
from agv.io.scenes import scenario_id, unpack_scene

MEASURED_COMMIT = "29d86e780e3f7e445248dee3b43b3882b6eb6a1a"


def main():
    root = Path("results/v2")
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    rows = list(csv.DictReader((root / "runs.csv").open(encoding="utf-8-sig")))
    assert len(rows) == manifest["validated_runs"] == 396
    for name, digest in manifest["sources"].items():
        raw = subprocess.check_output(["git", "show", f"{MEASURED_COMMIT}:src/agv/{name}"])
        assert hashlib.sha256(raw).hexdigest() == digest, name
    # Verify that localized later input/provenance hardening did not alter any
    # official experimental scene, including every heldout seed.
    scenes = {}
    for row in rows:
        key = (row["scenario"], int(row["seed"]))
        if key not in scenes:
            name, seed = key
            scenes[key] = (
                derived_scene("data/maps/warehouse-10-20-10-2-1.map", "test", seed, task_count=16)
                if name == "movingai_heldout"
                else example(**CONFIGS[name], seed=seed)
            )
        assert scenario_id(scenes[key]) == row["sha256"], key
    traces = 0
    for p in (root / "traces").glob("*.json"):
        entry = json.loads(p.read_text())
        scene = unpack_scene(entry)
        validate(scene, entry["result"])
        traces += 1
    print(
        json.dumps(
            dict(
                measurement_sources_match_git_snapshot=True,
                paired_rows=396,
                current_scenes_match=len(scenes),
                representative_traces_validated=traces,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
