"""The new holdout is frozen independently of the historical 200--219 set."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.experiments.architecture_options import (
    SCHEMA,
    _execute,
    benchmark,
    build_specs,
    check_protocol,
    freeze,
    summarize,
)


class ArchitectureOptionsTests(unittest.TestCase):
    def config(self):
        return {
            "maps": {"medium": {"size": "medium", "vehicles": 2}},
            "workloads": {"sparse": {"mode": "dynamic", "arrival": "uniform", "task_count": 2}},
            "baseline": "base",
            "solvers": {
                "base": {"base": "sipp_stream_dispatch"},
                "window": {
                    "base": "sipp_position_delay_dispatch",
                    "idle": {"stat_window": 100, "rebalance_period": 500},
                },
            },
        }

    def test_typed_specs_are_explicit_and_do_not_modify_registry_defaults(self):
        specs = build_specs(self.config())
        self.assertEqual(specs["window"].idle.stat_window, 100)
        self.assertEqual(specs["window"].idle.rebalance_period, 500)
        self.assertIsNone(specs["base"].idle.stat_window)
        with self.assertRaises((TypeError, ValueError)):
            config = self.config()
            config["solvers"]["window"]["idle"]["unknown"] = 1
            build_specs(config)

    def test_holdout_requires_matching_frozen_source_and_configuration(self):
        config, sources = self.config(), {"src/agv/example.py": "frozen"}
        frozen = dict(
            schema=SCHEMA, config=config, source_hashes=sources, holdout_seeds=list(range(30, 50))
        )
        check_protocol(config, "holdout", [30, 49], frozen, sources)
        for seeds, manifest, current in (
            ([200], frozen, sources),
            ([30], None, sources),
            ([30], frozen, {"src/agv/example.py": "changed"}),
            ([30, 30], frozen, sources),
            ([True], frozen, sources),
        ):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                check_protocol(config, "holdout", seeds, manifest, current)
        with self.assertRaises(ValueError):
            check_protocol(config, "development", [30], None, sources)

    def test_existing_output_is_rejected_before_any_expensive_work(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing.json"
            destination.write_text("keep")
            with patch("agv.experiments.architecture_options.build_specs") as build:
                with self.assertRaises(FileExistsError):
                    benchmark(destination, self.config(), seeds=[10])
                build.assert_not_called()
            self.assertEqual(destination.read_text(), "keep")

    def test_execution_validation_and_scoring_failures_remain_explicit_rows(self):
        config = self.config()
        payload = (
            "medium",
            config["maps"]["medium"],
            "sparse",
            config["workloads"]["sparse"],
            10,
            config,
        )
        for tool, stage in (
            ("run", "execution"),
            ("validate", "validation"),
            ("score_result", "scoring"),
        ):
            with (
                self.subTest(stage=stage),
                patch(
                    f"agv.experiments.architecture_options.{tool}",
                    side_effect=RuntimeError("deliberate probe failure"),
                ),
                # A sub-clock-tick failure legitimately measures zero CPU on Windows.
                patch("agv.experiments.architecture_options.time.process_time", return_value=10.0),
            ):
                rows = _execute(payload)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not row["valid"] for row in rows))
            self.assertTrue(all(row["failure_stage"] == stage for row in rows))
            self.assertTrue(all("deliberate probe failure" in row["audit_error"] for row in rows))
            self.assertTrue(all(row["cpu_seconds"] == 0 for row in rows))
            self.assertTrue(all(row["wall_seconds"] >= 0 for row in rows))

    def test_non_mapping_solver_result_is_retained_as_execution_failure(self):
        config = self.config()
        payload = (
            "medium",
            config["maps"]["medium"],
            "sparse",
            config["workloads"]["sparse"],
            10,
            config,
        )
        with patch("agv.experiments.architecture_options.run", return_value=[]):
            rows = _execute(payload)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row["valid"] for row in rows))
        self.assertTrue(all(row["failure_stage"] == "execution" for row in rows))
        self.assertTrue(all(row["weighted_score"] is None for row in rows))
        self.assertTrue(all("TypeError" in row["audit_error"] for row in rows))

    def test_summary_rejects_duplicate_missing_and_mismatched_controls(self):
        control = dict(
            map="medium", workload="sparse", seed=10, solver="base", scenario_sha256="same"
        )
        candidate = {**control, "solver": "window"}
        for rows in (
            [control, candidate, dict(candidate)],
            [candidate],
            [control, {**candidate, "scenario_sha256": "different"}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize(rows, "base")

    def test_small_real_paired_run_freeze_and_independent_holdout(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "agv.experiments.architecture_options.source_hashes", return_value={"test": "fixed"}
            ),
        ):
            root = Path(directory)
            config = self.config()
            manifest = freeze(config, root / "freeze.json")
            self.assertEqual(manifest["holdout_seeds"], list(range(30, 50)))
            dev = benchmark(root / "dev.json", config, seeds=[10])
            held = benchmark(
                root / "hold.json", config, split="holdout", seeds=[30], frozen=manifest
            )
            for report in (dev, held):
                self.assertEqual(len(report["rows"]), 2)
                self.assertTrue(all(row["valid"] for row in report["rows"]))
                self.assertEqual(report["summary"]["window/all"]["valid_pairs"], 1)
                self.assertTrue(
                    all(
                        math.isfinite(row[field]) and row[field] >= 0
                        for row in report["rows"]
                        for field in ("cpu_seconds", "wall_seconds")
                    )
                )
            self.assertEqual(json.loads((root / "dev.json").read_text())["seeds"], [10])
            with self.assertRaises(FileExistsError):
                freeze(config, root / "freeze.json")


if __name__ == "__main__":
    unittest.main()
