"""Small development fixtures test provenance, failures and paired arithmetic."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.experiments.bcrd import (
    PROTOCOL_SCHEMA,
    read_rows,
    run_benchmark,
    run_development,
    run_frozen,
    summarize,
    validate_protocol,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_bcrd", ROOT / "scripts/verify_bcrd.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
FIXTURE_HASHES = {"fixture.py": "unit-test-only"}


class BcrdExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="agv-bcrd-test-")
        cls.output = Path(cls.temporary.name) / "development"
        # Keep fixtures inexpensive and avoid dependence on concurrent edits.
        # Real run/validation/scoring are exercised; only snapshot inventory is mocked.
        with patch("agv.experiments.bcrd.source_hashes", return_value=FIXTURE_HASHES):
            cls.rows, cls.summary = run_development(
                cls.output,
                seeds=(10, 11),
                configs={"small_fixture": {"vehicles": 2, "task_count": 5}},
                solvers={
                    "G0": {"policy": "greedy"},
                    "G1": {"policy": "matching"},
                    "G2": {"policy": "bcrd", "max_batches": 0},
                },
            )
        cls.protocol = json.loads((cls.output / "protocol.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_two_development_fixtures_are_complete_and_reauditable(self):
        self.assertEqual(len(self.rows), 6)
        self.assertTrue(all(row["comparison_valid"] for row in self.rows))
        self.assertEqual(read_rows(self.output / "runs.csv"), self.rows)
        self.assertNotIn(b"\r\n", (self.output / "runs.csv").read_bytes())
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            audit = VERIFIER.verify(self.output)
        self.assertEqual(audit["rows"], 6)
        self.assertEqual(audit["independent_traces_validated"], 3)
        self.assertTrue(all(row["backend"] == "sipp" and not row["joint"] for row in self.rows))

    def test_paired_percent_not_official_reference_percent(self):
        rows = [copy.deepcopy(row) for row in self.rows if row["solver"] in ("G0", "G1")]
        for row in rows:
            row["weighted_score"] = 2.0 if row["solver"] == "G0" else 1.8
            row["p90_flow_time"] = 50 if row["solver"] == "G0" else 55
            row["cpu_seconds"] = 1 if row["solver"] == "G0" else 2
        protocol = copy.deepcopy(self.protocol)
        protocol["solvers"].pop("G2")
        result = summarize(rows, protocol)
        group = next(
            g for g in result["groups"] if g["scenario"] == "__all__" and g["solver"] == "G1"
        )
        self.assertAlmostEqual(group["paired_F_improvement_pct_mean"], 10)
        self.assertEqual(group["score_wins"], 2)
        self.assertEqual(group["p90_degradations"], 2)
        self.assertEqual(group["cpu_ratio_mean"], 2)
        self.assertTrue(
            all(abs(value - 10) < 1e-10 for value in group["paired_F_improvement_pct_95ci"])
        )

    def test_incomplete_pairs_remain_visible(self):
        rows = copy.deepcopy(self.rows)
        failed = next(r for r in rows if r["solver"] == "G1")
        failed["comparison_valid"] = failed["feasible"] = False
        failed["weighted_score"] = None
        result = summarize(rows, self.protocol)
        group = next(
            g for g in result["groups"] if g["scenario"] == "__all__" and g["solver"] == "G1"
        )
        self.assertEqual(group["runs"], 2)
        self.assertEqual(group["paired_successes"], 1)
        self.assertEqual(group["excluded_pairs"], 1)
        self.assertEqual(group["execution_failures"], 1)

    def test_source_changes_reject_finalization(self):
        output = Path(self.temporary.name) / "source-change"
        with patch(
            "agv.experiments.bcrd.source_hashes", side_effect=[FIXTURE_HASHES, {"changed": "yes"}]
        ):
            with self.assertRaisesRegex(RuntimeError, "Source changed"):
                run_development(
                    output,
                    seeds=(10,),
                    configs={"tiny": {"vehicles": 2, "task_count": 5}},
                    solvers={"G0": {"policy": "greedy"}},
                )
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "source_changed")
        self.assertFalse((output / "summary.json").exists())

    def test_algorithm_failure_is_retained_with_null_costs(self):
        from agv.dispatch.bcrd import run as real_run

        def sometimes_fail(scene, **params):
            if params["policy"] == "matching":
                raise RuntimeError("fixture policy failure")
            return real_run(scene, **params)

        output = Path(self.temporary.name) / "failed-policy"
        with (
            patch("agv.experiments.bcrd.source_hashes", return_value=FIXTURE_HASHES),
            patch("agv.experiments.bcrd.run_dispatch", side_effect=sometimes_fail),
        ):
            rows, summary = run_development(
                output,
                seeds=(10,),
                configs={"small": {"vehicles": 2, "task_count": 5}},
                solvers={"G0": {"policy": "greedy"}, "G1": {"policy": "matching"}},
            )
        failed = next(row for row in rows if row["solver"] == "G1")
        self.assertFalse(failed["comparison_valid"])
        self.assertEqual(failed["completed"], 0)
        self.assertIsNone(failed["weighted_score"])
        self.assertIsNone(failed["makespan"])
        group = next(
            g for g in summary["groups"] if g["scenario"] == "__all__" and g["solver"] == "G1"
        )
        self.assertEqual(group["excluded_pairs"], 1)
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            audit = VERIFIER.verify(output)
        self.assertEqual(audit["retained_failed_traces"], 1)

    def test_formal_run_requires_prefrozen_protocol_and_separate_seeds(self):
        with self.assertRaises(ValueError):
            run_benchmark(Path(self.temporary.name) / "never-created", split="holdout")
        with self.assertRaises(ValueError):
            run_frozen(Path(self.temporary.name) / "never-created", self.output / "protocol.json")
        protocol = dict(
            schema=PROTOCOL_SCHEMA,
            split="holdout",
            frozen=True,
            seeds=[30],
            configs={"small": {"task_count": 5, "vehicles": 2}},
            solvers={"G0": {"policy": "greedy"}},
        )
        validate_protocol(protocol, require_frozen=True)
        # Validation only: no held-out policy or scene is executed here.
        protocol["seeds"] = [10]
        with self.assertRaises(ValueError):
            validate_protocol(protocol, require_frozen=True)

    def test_tampered_artifact_is_rejected(self):
        copied = Path(self.temporary.name) / "tampered"
        import shutil

        shutil.copytree(self.output, copied)
        with (copied / "runs.csv").open("a") as file:
            file.write("tampered\n")
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            with self.assertRaisesRegex(ValueError, "Changed artifact"):
                VERIFIER.verify(copied)


if __name__ == "__main__":
    unittest.main()
