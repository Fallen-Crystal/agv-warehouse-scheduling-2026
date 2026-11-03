"""Solver/profile compatibility is validated in one place."""

import unittest

from agv.dispatch.registry import validate_solver


class SolverCompatibilityTests(unittest.TestCase):
    def test_single_compatibility_gate(self):
        self.assertIsNone(validate_solver("sipp_standby8_dispatch", "v9"))
        for name, profile in (
            ("sipp_standby8_dispatch", "v4"),
            ("sipp_stream_bcrd", "v9"),
            ("sipp_stream_dispatch", "legacy"),
            ("bcrd_budget", "v9.1"),
            ("not-a-solver", "legacy"),
        ):
            with self.subTest(name=name, profile=profile), self.assertRaises(ValueError):
                validate_solver(name, profile)


if __name__ == "__main__":
    unittest.main()
