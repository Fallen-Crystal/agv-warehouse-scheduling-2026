"""Fast default replay; the explicit CLI performs the complete 580-run gate."""

import os
import unittest

from tests.golden.record import load_golden, replay


class GoldenReplayTests(unittest.TestCase):
    def test_frozen_manifest_covers_all_solvers_and_development_seeds(self):
        manifest, data = load_golden()
        self.assertEqual(manifest["baseline_commit"], "cabc2120c15d5810823bdc1ea84b0a18eb846065")
        self.assertEqual(manifest["seeds"], list(range(10, 20)))
        self.assertEqual(manifest["errors"], [])
        self.assertEqual(manifest["case_count"], manifest["expected_case_count"])
        self.assertEqual(len(data["cases"]), 580)
        self.assertEqual(len(manifest["registered_solvers"]), 23)
        self.assertEqual(
            {case["solver"] for case in data["cases"]}, set(manifest["registered_solvers"])
        )
        self.assertTrue(all(case["feasible"] for case in manifest["cases"]))

    def test_pre_refactor_trajectories_are_preserved(self):
        # All seeds are replayed by `record.py replay`; keep normal unit runs
        # compact while retaining every solver and every supported profile.
        full = os.environ.get("AGV_GOLDEN_FULL") == "1"
        report = replay(seeds=None if full else {10})
        self.assertEqual(report["runs"], 580 if full else 58)
        self.assertEqual(report["differences"], [])


if __name__ == "__main__":
    unittest.main()
