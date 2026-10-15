"""Exercise V4 through installed CLI, viewer APIs, scene files and detail CSVs."""

import copy
import csv
import json
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.evaluation.validation import validate
from agv.io.exports import audit_details, export_details
from agv.io.scenes import pack_scene, scenario_id, unpack_scene
from agv.warehouse.layout import generate
from agv.web.app import calculate, calculate_batch, calculate_loaded


class V4EntrypointTests(unittest.TestCase):
    def run_cli(self, folder, *arguments):
        process = subprocess.run(
            [sys.executable, "-m", "agv", "run", *arguments],
            cwd=folder,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(json.loads(process.stdout)["feasible"])

    def test_cli_generates_v4_with_ten_vehicles_and_no_cutoff(self):
        with tempfile.TemporaryDirectory() as folder:
            self.run_cli(
                folder,
                "--profile",
                "v4",
                "--tasks",
                "2",
                "--vehicles",
                "10",
                "--output",
                "generated.json",
            )
            saved = json.loads((Path(folder) / "generated.json").read_text(encoding="utf-8"))
        scene = unpack_scene(saved)
        self.assertEqual(saved["format"], "agv-scene-v4")
        self.assertEqual(len(scene.homes), 10)
        self.assertIsNone(scene.horizon)
        self.assertTrue(saved["result"]["score_valid"])
        self.assertTrue(validate(scene, saved["result"]))

    def test_cli_loads_packed_finite_scene_without_regenerating_it(self):
        scene = generate(seed=7, task_count=2, vehicles=10, horizon=600, shelf_layers=5)
        archive = pack_scene(scene, config={"algorithm": "sipp_budget"})
        before = copy.deepcopy(archive)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "input.json").write_text(
                json.dumps(archive, ensure_ascii=False), encoding="utf-8"
            )
            self.run_cli(folder, "--input", "input.json", "--output", "rerun.json")
            saved = json.loads((Path(folder) / "rerun.json").read_text(encoding="utf-8"))
        self.assertEqual(archive, before)
        self.assertEqual(saved["scenario_sha256"], scenario_id(scene))
        self.assertEqual(saved["scenario"], json.loads(json.dumps(scene.to_dict())))
        self.assertEqual(unpack_scene(saved).to_dict(), scene.to_dict())
        self.assertTrue(validate(scene, saved["result"]))

    def test_viewer_calculation_preserves_layer_services_and_offline_score(self):
        entry = calculate(
            dict(profile="v4", vehicles=10, task_count=2, shelf_layers=5, algorithm="sipp_budget")
        )
        scene = unpack_scene(entry["scenario"])
        result = entry["result"]
        jobs = {job.id: job for job in scene.tasks}
        self.assertEqual(len(scene.homes), 10)
        self.assertTrue(result["feasible"])
        self.assertTrue(result["score_valid"])
        for event in result["events"]:
            job = jobs[event["task_id"]]
            self.assertEqual(event["pickup_end"] - event["pickup_arrival"], 2 * job.shelf_level)
            self.assertEqual(event["delivery_end"] - event["delivery_arrival"], 1)
        self.assertEqual(entry["scenario_sha256"], scenario_id(scene))
        self.assertTrue(validate(scene, result))

    def test_viewer_import_accepts_teammate_v3_envelope_and_recalculates_result(self):
        scene = generate(seed=4, task_count=2, horizon=600, obstacle_layout="columns_equipment")
        # The teammate's V4 model used the agv-scene-v3 envelope. Preserve its
        # explicit model/rule metadata; only the archive envelope differs.
        archive = pack_scene(scene, config={"algorithm": "sipp_budget"})
        archive["format"] = "agv-scene-v3"
        archive["result"] = {"weighted_score": -999, "feasible": False}
        before = copy.deepcopy(archive)
        entry = calculate_loaded(json.loads(json.dumps(archive)))
        self.assertEqual(archive, before)
        self.assertEqual(entry["scenario_sha256"], scenario_id(scene))
        self.assertEqual(entry["scenario"], scene.to_dict())
        self.assertEqual(entry["scenario"]["map_info"], scene.map_info)
        self.assertTrue(entry["result"]["feasible"])
        self.assertGreaterEqual(entry["result"]["weighted_score"], 0)
        self.assertTrue(validate(scene, entry["result"]))

    def test_viewer_rejects_invalid_profile_options_before_solver_execution(self):
        for options, message in (
            ({"profile": "v5"}, "profile"),
            ({"profile": "v4", "vehicles": 11}, "vehicles"),
            ({"profile": "v4", "shelf_layers": True}, "shelf_layers"),
        ):
            with self.subTest(options=options), patch("agv.web.app.run_named") as run:
                with self.assertRaisesRegex(ValueError, message):
                    calculate(options)
                run.assert_not_called()

    def test_viewer_import_limits_precede_model_parsing_and_explain_cli_alternative(self):
        raw = json.loads(json.dumps(generate(task_count=2, horizon=600).to_dict()))
        cases = (
            {"width": 97},
            {"height": 97},
            {"horizon": 1801},
            {"horizon": None},
            {"homes": [[i, 0] for i in range(11)]},
            {"tasks": [raw["tasks"][0]] * 61},
        )
        for change in cases:
            with self.subTest(change=list(change)):
                archive = {"format": "agv-scene-v3", "scenario": {**raw, **change}}
                with patch("agv.web.app.unpack_scene") as parse:
                    with self.assertRaisesRegex(ValueError, "页面导入限制") as error:
                        calculate_loaded(archive)
                    parse.assert_not_called()
                if change == {"horizon": None}:
                    self.assertIn("CLI", str(error.exception))

    def test_viewer_batch_retains_v4_profile_and_two_distinct_seed_results(self):
        request = dict(
            config=dict(profile="v4", vehicles=10, task_count=2, algorithm="sipp_budget"),
            start_seed=3,
            count=2,
        )
        before = copy.deepcopy(request)
        report = calculate_batch(request)
        self.assertEqual(request, before)
        self.assertEqual(report["seeds"], [3, 4])
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(len(report["entries"]), 2)
        self.assertNotEqual(
            report["rows"][0]["scenario_sha256"], report["rows"][1]["scenario_sha256"]
        )
        for seed, row, entry in zip(report["seeds"], report["rows"], report["entries"]):
            self.assertEqual(row["seed"], seed)
            self.assertEqual(entry["config"]["profile"], "v4")
            self.assertTrue(row["score_valid"])
            self.assertEqual(row["weighted_score"], entry["result"]["weighted_score"])
            self.assertTrue(validate(unpack_scene(entry["scenario"]), entry["result"]))
        summary = report["summaries"][0]
        self.assertEqual(summary["score_samples"], 2)
        self.assertAlmostEqual(
            summary["weighted_score_mean"],
            statistics.mean(row["weighted_score"] for row in report["rows"]),
        )

    def test_v4_detail_csv_roundtrip_audits_string_storage_identifiers(self):
        result = calculate(dict(profile="v4", task_count=2, algorithm="sipp_budget"))["result"]
        with tempfile.TemporaryDirectory() as folder:
            export_details(result, folder, "v4")
            audit_details(result, folder, "v4")
            task_file = Path(folder) / "v4_tasks.csv"
            with task_file.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                fields, rows = reader.fieldnames, list(reader)
            self.assertIn("storage_id", fields)
            self.assertIn("rack_bay", fields)
            for actual, expected in zip(rows, result["task_metrics"]):
                self.assertEqual(actual["storage_id"], expected["storage_id"])
                self.assertEqual(actual["rack_bay"], expected["rack_bay"])
                self.assertTrue(actual["storage_id"].endswith(f"-L{expected['shelf_level']:02d}"))
            rows[0]["storage_id"] += "-forged"
            with task_file.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "storage_id"):
                audit_details(result, folder, "v4")


if __name__ == "__main__":
    unittest.main()
