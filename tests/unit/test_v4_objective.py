import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from agv.dispatch.greedy import run
from agv.domain import Scenario, Task, example
from agv.evaluation.objective import (
    MODEL_VERSION,
    REFERENCE_POLICY,
    WEIGHTS,
    _cached_reference,
    objective_value,
    reference_context,
    score_result,
    validate_score,
)
from agv.simulation import Environment


def tiny(horizon=100, release=0):
    return Scenario(
        5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(10, (1, 1), (4, 1), release)], horizon
    ).check()


class V4ObjectiveTests(unittest.TestCase):
    def setUp(self):
        _cached_reference.cache_clear()

    def test_baseline_scores_one_and_preserves_inputs(self):
        scene = tiny()
        result = run(scene)
        before = copy.deepcopy(result)
        serialized_scene = copy.deepcopy(scene.to_dict())
        context = reference_context(scene)
        context_before = copy.deepcopy(context)
        scored = score_result(scene, result, context)
        self.assertEqual(objective_value(scored), 1)
        self.assertEqual(scored["objective_weights"], WEIGHTS)
        self.assertEqual(scored["model_version"], MODEL_VERSION)
        self.assertEqual(context["policy"], REFERENCE_POLICY)
        self.assertEqual(scored["estimated_energy"], 0.05 * result["moves"])
        self.assertEqual(scored["normalized_energy"], scored["normalized_distance"])
        self.assertTrue(validate_score(scene, scored, context))
        for name, value in result.items():
            self.assertEqual(scored[name], value)
        scored["paths"][0].append((0, 0))
        self.assertEqual(result, before)
        self.assertEqual(scene.to_dict(), serialized_scene)
        self.assertEqual(context, context_before)

    def test_weighted_score_uses_three_terms_without_energy_duplication(self):
        scene = tiny()
        env = Environment(scene)
        env.advance(3)
        env.assign([(0, 10)])
        while not env.done:
            env.advance()
        scored = score_result(scene, env.result())
        context = scored["normalization_reference"]
        expected = (
            0.5 * scored["makespan"] / context["time"]
            + 0.3 * scored["mean_flow_time"] / context["response"]
            + 0.2 * scored["moves"] / context["distance"]
        )
        self.assertAlmostEqual(scored["weighted_score"], expected)
        self.assertGreater(scored["weighted_score"], 1)
        self.assertTrue(validate_score(scene, scored))

    def test_empty_scene_has_zero_score(self):
        scene = example(task_count=0)
        scored = score_result(scene, run(scene))
        self.assertTrue(scored["score_valid"])
        self.assertEqual(objective_value(scored), 0)
        self.assertEqual(scored["normalization_reference"]["distance"], 0)
        self.assertTrue(validate_score(scene, scored))

    def test_failed_candidate_has_no_score_and_keeps_partial_metrics(self):
        scene = tiny()
        env = Environment(scene)
        env.assign([(0, 10)])
        env.advance(4)
        raw = env.result()
        scored = score_result(scene, raw)
        self.assertFalse(scored["score_valid"])
        self.assertIsNone(objective_value(scored))
        for key in (
            "weighted_score",
            "normalized_time",
            "normalized_response",
            "normalized_distance",
        ):
            self.assertIsNone(scored[key])
        self.assertEqual(scored["moves"], raw["moves"])
        self.assertTrue(validate_score(scene, scored))
        bad = copy.deepcopy(scored)
        bad["score_valid"] = True
        bad["weighted_score"] = 0
        with self.assertRaises(ValueError):
            validate_score(scene, bad)

    def test_failed_reference_does_not_produce_a_candidate_dependent_denominator(self):
        scene = tiny()
        candidate = run(scene)
        failed_reference = Environment(scene).result()
        with patch("agv.dispatch.greedy.run", return_value=failed_reference):
            scored = score_result(scene, candidate)
            self.assertFalse(scored["normalization_reference"]["available"])
            self.assertIsNone(scored["normalization_reference"]["time"])
            self.assertFalse(scored["score_valid"])
            self.assertIsNone(scored["weighted_score"])
            self.assertTrue(validate_score(scene, scored))

    def test_context_is_scene_specific_detached_and_not_exposed_to_policy(self):
        scene = tiny(release=3)
        before = Environment(scene).observe()
        context = reference_context(scene)
        raw = json.dumps(scene.to_dict(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(
            context["scenario_sha256"], hashlib.sha256(raw.encode("utf-8")).hexdigest()
        )
        context["distance"] = 999
        self.assertNotEqual(reference_context(scene)["distance"], 999)
        self.assertEqual(Environment(scene).observe(), before)
        self.assertNotIn("normalization_reference", before)
        self.assertEqual(before["pending"], [])
        other = tiny(release=4)
        with self.assertRaises(ValueError):
            score_result(other, run(other), reference_context(scene))

    def test_auditor_rejects_score_context_and_failure_field_tampering(self):
        scene = tiny()
        scored = score_result(scene, run(scene))
        edits = (
            ("weighted_score", 0),
            ("normalized_time", 0),
            ("normalized_response", float("nan")),
            ("normalized_distance", True),
            ("normalized_energy", 10),
            ("estimated_energy", 0),
            ("model_version", "forged"),
            ("objective_weights", {"time": 1, "response": 0, "distance": 0}),
            ("score_valid", False),
            ("comparison_valid", False),
            ("feasible", False),
        )
        for key, value in edits:
            with self.subTest(key=key):
                bad = copy.deepcopy(scored)
                bad[key] = value
                with self.assertRaises(ValueError):
                    validate_score(scene, bad)
        for key in (
            "time",
            "response",
            "distance",
            "energy",
            "available",
            "policy",
            "model_version",
            "scenario_sha256",
        ):
            with self.subTest(context_key=key):
                bad = copy.deepcopy(scored)
                value = bad["normalization_reference"][key]
                bad["normalization_reference"][key] = (
                    value + 1 if type(value) in (int, float) else "forged"
                )
                with self.assertRaises(ValueError):
                    validate_score(scene, bad)
                # Supplying the same forged context must not make it trustworthy.
                with self.assertRaises(ValueError):
                    validate_score(scene, bad, bad["normalization_reference"])
                with self.assertRaises(ValueError):
                    score_result(scene, run(scene), bad["normalization_reference"])
        bad = copy.deepcopy(scored)
        bad["diagnostics"]["execution_error"] = {"kind": "policy_error"}
        with self.assertRaises(ValueError):
            validate_score(scene, bad)

    def test_json_round_trip_and_invalid_execution(self):
        scene = tiny()
        scored = score_result(scene, run(scene))
        decoded = json.loads(json.dumps(scored, ensure_ascii=False, allow_nan=False))
        self.assertTrue(validate_score(scene, decoded))
        self.assertEqual(objective_value(decoded), objective_value(scored))
        bad = copy.deepcopy(decoded)
        bad["moves"] += 1
        with self.assertRaises(ValueError):
            score_result(scene, bad)
        self.assertIsNone(objective_value({"comparison_valid": False, "weighted_score": 0}))
        self.assertIsNone(
            objective_value(
                {"comparison_valid": True, "score_valid": True, "weighted_score": float("inf")}
            )
        )


if __name__ == "__main__":
    unittest.main()
