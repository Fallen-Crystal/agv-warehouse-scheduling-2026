"""Regression gates for replay identity, latency and experiment isolation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agv.core.objectives import LinearObjective
from agv.evaluation.objectives.linear_f import checked_score
from agv.experiments.cache import cache_key
from agv.experiments.wepa import (
    analyze,
    benchmark,
    freeze_protocol,
    load_protocol,
    reference_protocol,
)
from agv.runner.wepa import run
from tests.exact.fixtures import make


class WepaExperimentTests(unittest.TestCase):
    def config(self):
        original = reference_protocol()
        return dict(
            configuration=original["configuration"],
            objective=original["objective"],
            cases=original["cases"][:3],
            development=[original["cases"][0]["case"]],
            validation=[original["cases"][1]["case"]],
            sealed=[original["cases"][2]["case"]],
            methods=["gate", "gate_trigger"],
            seeds=[0],
            baseline="gate",
            timeout_seconds=30,
        )

    def test_none_latency_preserves_every_result_field(self):
        model = make("cross_out")
        self.assertEqual(
            run(model, "gate", 0), run(model, "gate", 0, latency=dict(kind="none", scale=0))
        )

    def test_fixed_and_measured_latency_replan_and_independently_validate(self):
        model = make("mixed_burst")
        objective = LinearObjective(vehicles=model["vehicles"])
        result = run(model, "hungarian", 0, latency=dict(kind="fixed", scale=3))
        self.assertTrue(checked_score(model, result, objective)["audit"]["valid"])
        events = result["decision_latency"]["events"]
        self.assertTrue(events)
        self.assertTrue(all(event["committed_at"] >= event["started_at"] + 3 for event in events))
        counter = iter(range(10000))
        with patch("agv.runner.wepa.process_time", side_effect=lambda: next(counter)):
            measured = run(model, "hungarian", 0, latency=dict(kind="measured", scale=1))
        self.assertTrue(checked_score(model, measured, objective)["audit"]["valid"])
        self.assertTrue(all(e["delay_steps"] == 1 for e in measured["decision_latency"]["events"]))

    def test_bad_latency_is_rejected(self):
        for value in (
            dict(kind="fixed", scale=1.2),
            dict(kind="measured", scale=True),
            dict(kind="measured", scale=float("nan")),
            dict(kind="magic", scale=1),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run(make("cross_out"), "gate", latency=value)

    def test_frozen_latency_is_validated_and_cannot_be_swapped(self):
        from agv.experiments.wepa import audit_trace, execute_case

        config = self.config()
        config["latency"] = dict(kind="fixed", scale=0)
        case = next(c for c in reference_protocol()["cases"] if c["case"] == "wepa-day45-bin4335")
        config.update(
            cases=[case],
            development=[case["case"]],
            validation=[],
            sealed=[],
            methods=["hungarian"],
            baseline="hungarian",
        )
        with tempfile.TemporaryDirectory() as directory:
            frozen = freeze_protocol(config, Path(directory) / "protocol.json")
            trace = execute_case(case, "hungarian", 0, latency=config["latency"])
            trace.update(
                implementation_sha256=frozen["sources"], protocol_sha256=frozen["protocol_sha256"]
            )
            audit_trace(trace, frozen)
            trace["result"]["decision_latency"]["model"]["scale"] = 1
            with self.assertRaisesRegex(ValueError, "latency differs"):
                audit_trace(trace, frozen)
            for bad in (
                dict(kind="fixed", scale=0.5),
                dict(kind="measured", scale=float("nan")),
                dict(kind="measured", scale=True),
            ):
                config["latency"] = bad
                with self.assertRaisesRegex(ValueError, "Invalid frozen"):
                    freeze_protocol(config, Path(directory) / "bad.json")

    def test_date_selection_gives_each_source_day_equal_weight(self):
        from agv.experiments.wepa import _selection_mean

        config = dict(
            development=["a", "b", "c"],
            cases=[
                dict(case="a", source_day=1),
                dict(case="b", source_day=1),
                dict(case="c", source_day=2),
            ],
        )
        sample = [dict(case=case, F=value) for case, value in zip("abc", (1, 3, 9))]
        self.assertEqual(_selection_mean(config, sample), 13 / 3)
        config["input_audit"] = dict(selection_unit="source_day")
        self.assertEqual(_selection_mean(config, sample), 5.5)

    def test_failed_plan_records_diagnostics_through_public_command(self):
        from agv.planning.sipp import SafeIntervalRouter
        from agv.policy.wepa import owned_batch
        from agv.world.wepa import World
        from agv.world.wepa_snapshot import observation

        model = make("cross_out")
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        job = world.ready()[0]
        with patch.object(world, "trip", return_value=None):
            self.assertEqual(owned_batch(observation(world), [job["id"]], {job["id"]: 0}), [])
        self.assertEqual(world.routing_failures, 1)
        self.assertNotIn(job["id"], world.assigned)

    def test_protocol_identity_source_and_disjoint_partitions(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("agv.experiments.wepa.source_identity", return_value={"unit": "original"}),
        ):
            path = Path(directory) / "frozen.json"
            frozen = freeze_protocol(self.config(), path)
            self.assertEqual(load_protocol(path), frozen)
            with patch("agv.experiments.wepa.source_identity", return_value={"unit": "changed"}):
                with self.assertRaisesRegex(ValueError, "Source"):
                    load_protocol(path)
            bad = copy.deepcopy(self.config())
            bad["sealed"] = bad["development"]
            with self.assertRaisesRegex(ValueError, "disjoint"):
                freeze_protocol(bad, Path(directory) / "bad.json")
            changed = json.loads(path.read_text())
            changed["config"]["seeds"] = [1]
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "identity"):
                load_protocol(path)

    def test_sealed_and_unselected_validation_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "frozen.json"
            freeze_protocol(self.config(), path)
            for split in ("sealed", "validation"):
                with self.subTest(split=split), self.assertRaises(ValueError):
                    benchmark(path, split, root / split)
                self.assertFalse((root / split).exists())

    def test_different_objectives_never_mix_in_analysis_or_cache_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = freeze_protocol(self.config(), root / "protocol.json")
            wrong = dict(
                protocol_sha256=protocol["protocol_sha256"],
                objective_id="relative-f",
                split="development",
                complete=True,
                rows=[],
            )
            (root / "wrong.json").write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError, "different objective"):
                analyze(root / "protocol.json", root / "wrong.json", root / "out.json")
            a = LinearObjective()
            b = LinearObjective(weights=(0.4, 0.4, 0.2))
            self.assertNotEqual(a.objective_id, b.objective_id)
            self.assertNotEqual(
                cache_key(dict(objective_id=a.objective_id)),
                cache_key(dict(objective_id=b.objective_id)),
            )

    def test_cache_rejects_another_solver_latency_and_forged_row_metrics(self):
        from agv.experiments.wepa import audit_trace, execute_case

        config = self.config()
        case = next(c for c in reference_protocol()["cases"] if c["case"] == "wepa-day45-bin4335")
        config.update(
            cases=[case],
            development=[case["case"]],
            validation=[],
            sealed=[],
            methods=["gate", "hungarian"],
        )
        with tempfile.TemporaryDirectory() as directory:
            frozen = freeze_protocol(config, Path(directory) / "protocol.json")
            trace = execute_case(case, "hungarian", 0)
            trace.update(
                implementation_sha256=frozen["sources"], protocol_sha256=frozen["protocol_sha256"]
            )
            audit_trace(trace, frozen, expected=(case["case"], "hungarian", 0))
            with self.assertRaisesRegex(ValueError, "identity"):
                audit_trace(trace, frozen, expected=(case["case"], "gate", 0))
            changed = copy.deepcopy(trace)
            changed["row"]["T"] += 1
            with self.assertRaisesRegex(ValueError, "row metrics"):
                audit_trace(changed, frozen)
            changed = copy.deepcopy(trace)
            changed["result"]["decision_latency"] = dict(model=dict(kind="fixed", scale=1))
            with self.assertRaisesRegex(ValueError, "latency"):
                audit_trace(changed, frozen)


if __name__ == "__main__":
    unittest.main()
