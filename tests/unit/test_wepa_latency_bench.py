"""The supplemental harness must preserve sealed inputs and plan identity."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.experiments.wepa import freeze_protocol, reference_protocol

PATH = Path(__file__).resolve().parents[2] / "scripts/benchmark_wepa_latency.py"
SPEC = importlib.util.spec_from_file_location("latency_benchmark", PATH)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


class LatencyBenchmarkTests(unittest.TestCase):
    def config(self):
        original = reference_protocol()
        cases = original["cases"][:3]
        return dict(
            configuration=original["configuration"],
            objective=original["objective"],
            cases=cases,
            development=[cases[0]["case"]],
            validation=[cases[1]["case"]],
            sealed=[cases[2]["case"]],
            methods=["gate"],
            baseline="gate",
            seeds=[0],
            timeout_seconds=30,
        )

    def test_configuration_is_detached_and_does_not_repartition(self):
        base = dict(config=self.config())
        before = copy.deepcopy(base)
        config = bench.configuration(base)
        self.assertEqual(base, before)
        for key in ("cases", "development", "validation", "sealed"):
            self.assertEqual(config[key], base["config"][key])
        self.assertEqual(config["latency"], dict(kind="measured", scale=1))
        self.assertEqual(config["methods"], ["gate", "gate_anchor", "hungarian"])

    def test_serial_measurement_keeps_failures_and_never_opens_sealed(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(bench, "RUNS", Path(directory)),
        ):
            root = Path(directory)
            base = root / "base.json"
            freeze_protocol(self.config(), base)
            protocol, plan = root / "latency.json", root / "plan.json"
            bench.prepare(base, protocol, plan)
            observed = []

            def failed_trial(payload):
                observed.append(payload)
                return dict(
                    case=payload[1],
                    profile=payload[2],
                    seed=payload[3],
                    status="failed",
                    valid=False,
                )

            with patch.object(bench, "_trial", side_effect=failed_trial):
                summary = bench.run(base, protocol, plan, root / "output")
            self.assertEqual(summary["failed"], 3)
            self.assertEqual(len(observed), 3)
            self.assertTrue(all(item[1] in self.config()["validation"] for item in observed))
            self.assertTrue(all(item[-1] is None for item in observed))
            with self.assertRaises(FileExistsError):
                bench.run(base, protocol, plan, root / "output")
            changed = json.loads(plan.read_text())
            changed["latency"]["scale"] = 2
            plan.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "plan"):
                bench.run(base, protocol, plan, root / "tampered")
            self.assertFalse((root / "tampered").exists())

    def test_full_outputs_cannot_escape_runs(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(bench, "RUNS", Path(directory) / "runs"),
        ):
            with self.assertRaisesRegex(ValueError, "runs directory"):
                bench.ignored(Path(directory) / "publish")


if __name__ == "__main__":
    unittest.main()
