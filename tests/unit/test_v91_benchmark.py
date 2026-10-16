"""Small real executions exercise V9.1 provenance and independent auditing."""

import copy
import csv
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.dispatch.greedy import run as run_greedy
from agv.experiments.v91_bench import (
    build_scene,
    default_protocol,
    read_rows,
    run_benchmark,
    source_hashes,
    summarize,
    validate_protocol,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_v91", ROOT / "scripts/verify_v91.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
FIXTURE_HASHES = {"src/agv/fixture.py": "unit-test-only"}


def fixture_protocol():
    protocol = default_protocol()
    protocol.update(
        seeds=[10, 11],
        maps={"small": {"size": "medium", "vehicles": 1}},
        workloads={"dense_static": {"mode": "static", "task_count": 2}},
        solvers={"G0": "sipp_stream_dispatch", "G1": "sipp_stream_matching"},
        bootstrap={"resamples": 100, "seed": 7},
    )
    return protocol


class V91BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="agv-v91-bench-")
        cls.output = Path(cls.temporary.name) / "development"
        cls.protocol = fixture_protocol()
        with (
            patch("agv.experiments.v91_bench.source_hashes", return_value=FIXTURE_HASHES),
            patch("agv.experiments.v91_bench._raw", side_effect=lambda name, s: run_greedy(s)),
        ):
            cls.rows, cls.summary = run_benchmark(cls.output, cls.protocol)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_complete_matrix_real_validation_and_independent_audit(self):
        self.assertEqual(len(self.rows), 4)
        self.assertTrue(all(row["comparison_valid"] for row in self.rows))
        self.assertEqual(read_rows(self.output / "runs.csv"), self.rows)
        self.assertNotIn(b"\r\n", (self.output / "runs.csv").read_bytes())
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            audit = VERIFIER.verify(self.output)
        self.assertEqual(audit["rows"], 4)
        self.assertEqual(audit["independent_traces_validated"], 2)
        for row in self.rows:
            self.assertLessEqual(row["T_lower_bound"], row["makespan"])
            self.assertLessEqual(row["R_lower_bound"], row["mean_flow_time"])
            self.assertLessEqual(row["D_lower_bound"], row["moves"])
            expected_f_bound = sum(
                weight * row[key + "_lower_bound"] / row["reference_" + key]
                for weight, key in ((0.5, "T"), (0.3, "R"), (0.2, "D"))
            )
            self.assertAlmostEqual(row["F_lower_bound"], expected_f_bound)
            self.assertAlmostEqual(
                row["F_gap_pct"], 100 * (row["weighted_score"] / expected_f_bound - 1)
            )

    def test_unknown_and_historical_registry_names_rejected_before_output(self):
        for name in ("sipp_does_not_exist", "sipp_joint"):
            protocol = fixture_protocol()
            protocol["solvers"]["G1"] = name
            output = Path(self.temporary.name) / name
            with self.assertRaises(ValueError):
                run_benchmark(output, protocol)
            self.assertFalse(output.exists())

    def test_violated_bound_is_retained_as_failure_without_negative_gaps(self):
        protocol = fixture_protocol()
        protocol.update(seeds=[10], solvers={"G0": "sipp_stream_dispatch"})
        output = Path(self.temporary.name) / "violated-bound"
        with (
            patch("agv.experiments.v91_bench.source_hashes", return_value=FIXTURE_HASHES),
            patch("agv.experiments.v91_bench._raw", side_effect=lambda name, s: run_greedy(s)),
            patch(
                "agv.experiments.v91_bench._bounds",
                return_value={"T": 1e9, "R": 0, "D": 0, "method": "invalid-fixture"},
            ),
        ):
            rows, _ = run_benchmark(output, protocol)
        row = rows[0]
        self.assertFalse(row["comparison_valid"])
        self.assertTrue(row["reason"].startswith("bound_error:"))
        self.assertIsNone(row["weighted_score"])
        self.assertIsNotNone(row["F_lower_bound"])
        for field in ("F_gap_pct", "T_gap_pct", "R_gap_pct", "D_gap_pct"):
            self.assertIsNone(row[field])
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            self.assertEqual(VERIFIER.verify(output)["retained_failed_traces"], 1)

    def test_f_bound_and_gap_tampering_detected_independently(self):
        for field in ("F_lower_bound", "F_gap_pct"):
            with self.subTest(field=field):
                output = Path(self.temporary.name) / ("tampered-" + field)
                shutil.copytree(self.output, output)
                rows = read_rows(output / "runs.csv")
                rows[0][field] += 1
                path = output / "runs.csv"
                with path.open("w", encoding="utf-8", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                manifest_path = output / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["artifact_hashes"]["runs.csv"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
                    with self.assertRaisesRegex(ValueError, "Independent calculation"):
                        VERIFIER.verify(output)

    def test_paired_effects_use_same_backend_control(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row["weighted_score"] = 2 if row["solver"] == "G0" else 1.8
            row["cpu_seconds"] = 1 if row["solver"] == "G0" else 2
            row["p90_flow_time"] = 50 if row["solver"] == "G0" else 55
        group = next(
            g
            for g in summarize(rows, self.protocol)["groups"]
            if g["scenario"] == "__all__" and g["solver"] == "G1"
        )
        self.assertAlmostEqual(group["paired_F_improvement_pct_mean"], 10)
        self.assertEqual(group["score_wins"], 2)
        self.assertEqual(group["p90_degradations"], 2)
        self.assertEqual(group["cpu_ratio_mean"], 2)
        self.assertTrue(all(abs(v - 10) < 1e-10 for v in group["paired_F_improvement_pct_95ci"]))

    def test_algorithm_failure_retained_and_excluded(self):
        protocol = fixture_protocol()
        protocol["seeds"] = [10]

        def fail_matching(name, scene):
            if name == "sipp_stream_matching":
                raise RuntimeError("fixture failure")
            return run_greedy(scene)

        output = Path(self.temporary.name) / "failed"
        with (
            patch("agv.experiments.v91_bench.source_hashes", return_value=FIXTURE_HASHES),
            patch("agv.experiments.v91_bench._raw", side_effect=fail_matching),
        ):
            rows, summary = run_benchmark(output, protocol)
        failed = next(r for r in rows if r["solver"] == "G1")
        self.assertFalse(failed["comparison_valid"])
        self.assertIsNone(failed["weighted_score"])
        self.assertIsNone(failed["moves"])
        group = next(
            g for g in summary["groups"] if g["scenario"] == "__all__" and g["solver"] == "G1"
        )
        self.assertEqual(group["excluded_pairs"], 1)
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            self.assertEqual(VERIFIER.verify(output)["retained_failed_traces"], 1)

    def test_source_change_interrupts_without_summary(self):
        output = Path(self.temporary.name) / "changed"
        protocol = fixture_protocol()
        protocol["seeds"] = [10]
        with (
            patch(
                "agv.experiments.v91_bench.source_hashes",
                side_effect=[FIXTURE_HASHES] * 4 + [{"changed": "yes"}],
            ),
            patch("agv.experiments.v91_bench._raw", side_effect=lambda name, s: run_greedy(s)),
        ):
            with self.assertRaisesRegex(RuntimeError, "Source changed"):
                run_benchmark(output, protocol)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "source_changed")
        self.assertEqual(manifest["recorded_runs"], 2)
        self.assertFalse((output / "summary.json").exists())

    def test_holdout_freeze_and_unseen_seed_ranges(self):
        protocol = default_protocol("holdout")
        validate_protocol(protocol, require_frozen=True)
        self.assertEqual(protocol["seeds"], list(range(200, 220)))
        for seed in (10, 30, 39, 60, 62, 101, 103):
            protocol["seeds"] = [seed]
            with self.assertRaises(ValueError):
                validate_protocol(protocol)
        protocol["seeds"] = [200]
        protocol["frozen"] = False
        with self.assertRaisesRegex(ValueError, "frozen"):
            validate_protocol(protocol)

    def test_stage0_astar_reference_is_excluded_from_sipp_effects(self):
        protocol = copy.deepcopy(self.protocol)
        protocol.update(stage="stage0", solvers={"G0": "sipp_stream_dispatch", "A0": "baseline"})
        validate_protocol(protocol)
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row["solver"] == "G1":
                row.update(solver="A0", registry_name="baseline", backend="astar")
        group = next(
            g
            for g in summarize(rows, protocol)["groups"]
            if g["scenario"] == "__all__" and g["solver"] == "A0"
        )
        self.assertEqual(group["successes"], 2)
        self.assertEqual(group["paired_successes"], 0)
        self.assertEqual(group["comparison_role"], "score_reference_diagnostic")
        self.assertIsNone(group["paired_F_improvement_pct_mean"])
        protocol.pop("stage")
        with self.assertRaises(ValueError):
            validate_protocol(protocol)

    def test_synthetic_release_scaling_preserves_shared_destination(self):
        config = {"size": "medium", "vehicles": 1}
        options = {
            "mode": "dynamic",
            "arrival": "uniform",
            "task_count": 3,
            "delivery_pattern": "shared",
        }
        original = build_scene(config, options, 10)
        scaled = build_scene(config, {**options, "release_scale": 20}, 10)
        self.assertEqual(
            [j.release for j in scaled.tasks], [20 * j.release for j in original.tasks]
        )
        self.assertEqual(scaled.order_stream_end, original.order_stream_end * 20)
        self.assertEqual(len({j.delivery for j in scaled.tasks}), 1)
        self.assertTrue(scaled.is_v9_1)

    def test_lf_hash_normalizes_line_endings(self):
        root = Path(self.temporary.name) / "lf"
        folder = root / "src/agv"
        folder.mkdir(parents=True)
        path = folder / "fixture.py"
        path.write_bytes(b"a\r\nb\r\n")
        with patch("agv.experiments.v91_bench.ROOT", root):
            first = source_hashes()
            path.write_bytes(b"a\nb\n")
            self.assertEqual(source_hashes(), first)

    def test_summary_tampering_detected_even_if_artifact_hash_updated(self):
        output = Path(self.temporary.name) / "tampered"
        shutil.copytree(self.output, output)
        path = output / "summary.json"
        saved = json.loads(path.read_text())
        saved["groups"][0]["paired_successes"] += 1
        path.write_text(json.dumps(saved), encoding="utf-8")
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["artifact_hashes"]["summary.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with patch.object(VERIFIER, "source_hashes", return_value=FIXTURE_HASHES):
            with self.assertRaisesRegex(ValueError, "Independent calculation"):
                VERIFIER.verify(output)


if __name__ == "__main__":
    unittest.main()
