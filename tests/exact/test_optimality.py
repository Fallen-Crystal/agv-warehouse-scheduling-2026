"""Optional CP-SAT certificates for the four reduced static warehouse cases."""

import importlib.util
import json
import unittest
from pathlib import Path

if importlib.util.find_spec("ortools") is None:
    raise unittest.SkipTest("Optional exact reference requires pip install -e .[exact]")

from agv.core.objectives import LinearObjective
from agv.evaluation.objectives.linear_f import checked_score
from agv.runner.wepa import run
from tests.exact.fixtures import make
from tests.exact.joint import solve


class WepaExactOptimalityTests(unittest.TestCase):
    def check_case(self, name):
        expected = json.loads(Path(__file__).with_name("optima.json").read_text(encoding="utf-8"))[
            "cases"
        ][name]
        model, objective = make(name), LinearObjective(vehicles=2)
        incumbent = run(model, "gate", seed=0, objective=objective)
        proof, result = solve(model, objective, incumbent, seconds=60)
        self.assertTrue(expected["optimal"])
        self.assertTrue(proof["optimal"], proof)
        self.assertEqual(proof["objective_integer"], proof["bound_integer"])
        self.assertEqual(proof["objective_integer"], expected["objective_integer"])
        self.assertEqual(proof["coefficient_scale"], expected["coefficient_scale"])
        self.assertIsNotNone(result)
        exact_score = checked_score(model, result, objective)
        self.assertTrue(exact_score["audit"]["valid"])
        self.assertAlmostEqual(exact_score["F_linear_v2"], expected["F_reference"], places=12)
        for profile in (
            "gate",
            "hungarian",
            "hga",
            "gate_anchor",
            "gate_anchor_tail",
            "gate_tail",
            "gate_trigger",
        ):
            with self.subTest(profile=profile):
                candidate = run(model, profile, seed=0, objective=objective)
                score = checked_score(model, candidate, objective)
                self.assertTrue(score["audit"]["valid"])
                reference_profile = profile if profile in expected["profiles"] else "gate"
                self.assertAlmostEqual(
                    score["F_linear_v2"], expected["profiles"][reference_profile]["F"], places=12
                )
                # The archived Hungarian control has known positive gaps on two cases.
                if profile != "hungarian":
                    self.assertAlmostEqual(
                        score["F_linear_v2"], exact_score["F_linear_v2"], places=12
                    )

    def test_cross_out(self):
        self.check_case("cross_out")

    def test_mixed(self):
        self.check_case("mixed")

    def test_layers(self):
        self.check_case("layers")

    def test_mixed_burst(self):
        self.check_case("mixed_burst")


if __name__ == "__main__":
    unittest.main()
