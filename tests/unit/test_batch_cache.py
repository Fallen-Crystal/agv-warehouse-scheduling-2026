"""Cache integrity and ordered process execution use real independent auditing."""

import copy
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agv.evaluation.validation import validate
from agv.experiments import v91_bench
from agv.experiments.cache import ResultCache, cache_identity, cache_key
from agv.registry import SOLVERS
from agv.runner.batch import BatchTask, run_batch


def seeded_worker(value):
    return value, random.random()


def failing_worker(value):
    raise ValueError(f"worker failure: {value}")


def fixture_protocol():
    protocol = v91_bench.default_protocol()
    protocol.update(
        seeds=[10],
        maps={"medium": {"size": "medium", "vehicles": 1}},
        workloads={"dense_static": {"mode": "static", "task_count": 2}},
        solvers={"G0": "sipp_stream_dispatch"},
        bootstrap={"resamples": 100, "seed": 7},
    )
    return protocol


class OrderedBatchTests(unittest.TestCase):
    def test_serial_parallel_are_identical_and_do_not_change_callers_rng(self):
        tasks = [BatchTask(seed, str(seed)) for seed in (17, 10, 13)]
        state = random.getstate()
        serial = list(run_batch(tasks, seeded_worker))
        self.assertEqual(random.getstate(), state)
        self.assertEqual(serial, list(run_batch(tasks, seeded_worker, workers=2)))
        self.assertEqual([item[0] for item in serial], ["17", "10", "13"])
        self.assertNotEqual(serial[0][1], serial[1][1])

    def test_worker_exceptions_propagate_in_both_execution_modes(self):
        state = random.getstate()
        for workers in (1, 2):
            with (
                self.subTest(workers=workers),
                self.assertRaisesRegex(ValueError, "worker failure"),
            ):
                list(run_batch([BatchTask(10, "broken")], failing_worker, workers=workers))
        self.assertEqual(random.getstate(), state)

    def test_invalid_tasks_and_worker_counts_rejected(self):
        for workers in (0, 33, True, 1.5):
            with self.assertRaises(ValueError):
                list(run_batch([], seeded_worker, workers=workers))
        with self.assertRaises(TypeError):
            list(run_batch([BatchTask(True, None)], seeded_worker))

    def test_real_v91_serial_parallel_rows_and_traces_match_except_clock_measurements(self):
        protocol = fixture_protocol()
        protocol.update(
            seeds=[10, 11], solvers={"G0": "sipp_stream_dispatch", "G1": "sipp_stream_matching"}
        )
        with tempfile.TemporaryDirectory(prefix="agv-process-matrix-") as directory:
            root = Path(directory)
            serial, _ = v91_bench.run_benchmark(root / "serial", protocol, no_cache=True)
            parallel, _ = v91_bench.run_benchmark(
                root / "parallel", protocol, workers=2, no_cache=True
            )

            def strip_clocks(rows):
                return [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in ("cpu_seconds", "wall_seconds", "measurement_environment")
                    }
                    for row in rows
                ]

            self.assertEqual(strip_clocks(serial), strip_clocks(parallel))
            for path in (root / "serial" / "traces").glob("*.json"):
                self.assertEqual(
                    path.read_bytes(), (root / "parallel" / "traces" / path.name).read_bytes()
                )


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agv-cache-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cache_dir = self.root / "cache"
        self.protocol = fixture_protocol()
        self.sources = {"src/agv/fixture.py": "fixture-source", "model.json": "model-v1"}
        self.scene = v91_bench.build_scene(
            self.protocol["maps"]["medium"], self.protocol["workloads"]["dense_static"], 10
        )

    def identity(self, **changes):
        inputs = dict(
            scene=self.scene,
            spec=SOLVERS["sipp_stream_matching"],
            seed=10,
            config=dict(mode="static", map=dict(size="medium", vehicles=1)),
            sources=self.sources,
            resources={"model.json": "model-v1"},
        )
        inputs.update(changes)
        return cache_identity(**inputs)

    def run_bench(self, name, **kwargs):
        with patch("agv.experiments.v91_bench.source_hashes", return_value=self.sources):
            return v91_bench.run_benchmark(
                self.root / name, self.protocol, cache_dir=self.cache_dir, **kwargs
            )

    def test_key_covers_scene_spec_seed_complete_configuration_sources_and_resources(self):
        original = cache_key(self.identity())
        scene = copy.deepcopy(self.scene)
        scene.tasks = [replace(scene.tasks[0], release=1), *scene.tasks[1:]]
        spec = SOLVERS["sipp_stream_matching"]
        changed = [
            self.identity(scene=scene),
            self.identity(spec=replace(spec, assign=replace(spec.assign, delay=True))),
            self.identity(seed=11),
            self.identity(config=dict(mode="dynamic", map=dict(size="medium", vehicles=1))),
            self.identity(config=dict(mode="static", map=dict(size="medium", vehicles=2))),
            self.identity(sources={**self.sources, "src/agv/fixture.py": "source-v2"}),
            self.identity(resources={"model.json": "model-v2"}),
        ]
        self.assertTrue(all(cache_key(identity) != original for identity in changed))
        reordered = self.identity(config=dict(map=dict(vehicles=1, size="medium"), mode="static"))
        self.assertEqual(cache_key(reordered), original)

    def test_miss_hit_refresh_and_no_cache_preserve_measured_result_provenance(self):
        raw = v91_bench._raw
        with patch("agv.experiments.v91_bench._raw", wraps=raw) as execute:
            first, _ = self.run_bench("cold")
            self.assertEqual(execute.call_count, 1)
            with patch("agv.experiments.v91_bench.validate", wraps=validate) as audit:
                second, summary = self.run_bench("warm")
                self.assertGreater(audit.call_count, 0)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(first[0]["cache_status"], "miss")
            self.assertEqual(second[0]["cache_status"], "hit")
            self.assertEqual(second[0]["timing_origin"], "cached")
            self.assertEqual(
                second[0]["measurement_environment"], first[0]["measurement_environment"]
            )
            self.assertEqual(summary["cache"]["hits"], 1)
            for field in first[0]:
                if field not in ("cache_status", "timing_origin"):
                    self.assertEqual(first[0][field], second[0][field], field)
            refreshed, _ = self.run_bench("refresh", refresh=True)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(refreshed[0]["cache_status"], "refresh")
            uncached, _ = self.run_bench("disabled", no_cache=True)
            self.assertEqual(execute.call_count, 3)
            self.assertEqual(uncached[0]["cache_status"], "disabled")
            self.assertEqual(uncached[0]["timing_origin"], "fresh")

    def test_invalid_cache_metadata_and_trace_are_recomputed_even_with_valid_digest(self):
        self.run_bench("initial")
        path = next(self.cache_dir.glob("*.json"))
        saved = json.loads(path.read_text(encoding="utf-8"))
        cases = (
            "invalid-json",
            "wrong-identity",
            "changed-payload",
            "forged-trace",
            "bad-environment",
        )
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                entry = copy.deepcopy(saved)
                if case == "invalid-json":
                    path.write_text("{partial", encoding="utf-8")
                else:
                    if case == "wrong-identity":
                        entry["identity"]["seed"] += 1
                    elif case == "bad-environment":
                        entry["payload"]["measurement_environment"]["workers"] = True
                        entry["payload_sha256"] = cache_key(entry["payload"])
                    else:
                        entry["payload"]["result"]["moves"] += 1
                        entry["validation_passed"] = True
                        if case == "forged-trace":
                            entry["payload_sha256"] = cache_key(entry["payload"])
                    path.write_text(json.dumps(entry), encoding="utf-8")
                with patch("agv.experiments.v91_bench._raw", wraps=v91_bench._raw) as execute:
                    rows, _ = self.run_bench(f"recovered-{index}")
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(rows[0]["cache_status"], "invalid")
                self.assertTrue(rows[0]["comparison_valid"])

    def test_cache_retains_original_measurement_machine_when_reused_elsewhere(self):
        with patch("agv.experiments.v91_bench.platform.platform", return_value="original-platform"):
            first, _ = self.run_bench("original-machine")
        with patch("agv.experiments.v91_bench._raw", wraps=v91_bench._raw) as execute:
            reused, _ = self.run_bench("current-machine")
        self.assertEqual(execute.call_count, 0)
        environment = json.loads(reused[0]["measurement_environment"])
        self.assertEqual(environment["platform"], "original-platform")
        self.assertEqual(reused[0]["cpu_seconds"], first[0]["cpu_seconds"])
        diagnostics = json.loads((self.root / "current-machine" / "diagnostics.jsonl").read_text())
        self.assertEqual(diagnostics["measurement_environment"], environment)

    def test_atomic_store_leaves_no_temporary_files_and_missing_cache_is_a_miss(self):
        cache = ResultCache(self.cache_dir)
        identity = self.identity()
        self.assertEqual(cache.load(identity, lambda payload: None), (None, "miss"))
        cache.store(identity, dict(result="first"))
        cache.store(identity, dict(result="second"))
        self.assertEqual(len(list(self.cache_dir.iterdir())), 1)
        payload, status = cache.load(identity, lambda payload: None)
        self.assertEqual(status, "hit")
        self.assertEqual(payload, dict(result="second"))

    def test_source_cache_path_and_conflicting_modes_rejected_before_output(self):
        output = self.root / "not-created"
        for options in (
            dict(cache_dir=v91_bench.ROOT / "src/agv/cache"),
            dict(no_cache=True, refresh=True),
        ):
            with self.assertRaises(ValueError):
                v91_bench.run_benchmark(output, self.protocol, **options)
            self.assertFalse(output.exists())

    def test_algorithm_failure_stays_in_matrix_and_is_not_cached(self):
        with patch("agv.experiments.v91_bench._raw", side_effect=RuntimeError("test failure")):
            rows, _ = self.run_bench("algorithm-failure")
        self.assertFalse(rows[0]["execution_valid"])
        self.assertIn("algorithm_error:RuntimeError:test failure", rows[0]["reason"])
        self.assertFalse(self.cache_dir.exists())

    def test_worker_failure_leaves_interrupted_manifest_and_no_completed_summary(self):
        with patch("agv.experiments.v91_bench._run_instance", side_effect=RuntimeError("worker")):
            with self.assertRaisesRegex(RuntimeError, "worker"):
                self.run_bench("interrupted")
        output = self.root / "interrupted"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "interrupted")
        self.assertEqual(manifest["recorded_runs"], 0)
        self.assertFalse((output / "summary.json").exists())

    def test_source_change_prevents_publishing_cache_entries(self):
        with patch(
            "agv.experiments.v91_bench.source_hashes",
            side_effect=[self.sources, self.sources, {"changed": "source"}],
        ):
            with self.assertRaises(v91_bench.SourceChanged):
                v91_bench.run_benchmark(
                    self.root / "changed", self.protocol, cache_dir=self.cache_dir
                )
        self.assertFalse(self.cache_dir.exists())
        manifest = json.loads((self.root / "changed" / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "source_changed")


if __name__ == "__main__":
    unittest.main()
