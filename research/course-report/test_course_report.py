"""Regression tests for the 12-order course-report case on the frozen runtime."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cases import load_case

HERE = Path(__file__).resolve().parent


class CourseReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(prefix="agv-course-test-") as directory:
            cls.joint = cls.run_case(directory, "joint")
            cls.zero = cls.run_case(directory, "counterfactual", branch_budget=0)
            cls.full = cls.run_case(directory, "counterfactual")

    @staticmethod
    def run_case(directory, mode, branch_budget=None):
        output = Path(directory) / f"{mode}-{branch_budget}.json"
        command = [sys.executable, str(HERE / "run.py"), "--case", "size12",
                   "--mode", mode, "--seed", "0", "--output", str(output)]
        if branch_budget is not None:
            command.extend(("--branch-budget", str(branch_budget)))
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        return json.loads(output.read_text(encoding="utf-8"))

    def test_size12_passes_independent_replay_and_matches_report(self):
        for output, score, finish, distance in (
            (self.joint, 0.15167592592592594, 159, 922),
            (self.full, 0.14046296296296296, 140, 908),
        ):
            with self.subTest(mode=output["summary"]["mode"]):
                summary = output["summary"]
                self.assertTrue(summary["valid"])
                self.assertTrue(output["trajectory"]["valid"])
                self.assertEqual(len(output["trajectory"]["completed"]), 12)
                self.assertAlmostEqual(summary["F"], score, places=12)
                self.assertEqual((summary["T"], summary["D"]), (finish, distance))

    def test_zero_branch_budget_matches_joint_trajectory(self):
        self.assertEqual(self.zero["summary"]["F"], self.joint["summary"]["F"])
        for field in ("paths", "labels", "records", "decisions", "final_stock"):
            with self.subTest(field=field):
                self.assertEqual(self.zero["trajectory"][field], self.joint["trajectory"][field])

    def test_counterfactual_preserves_open_prefix(self):
        close_at = load_case("size12")["close_at"]
        joint, full = self.joint["trajectory"], self.full["trajectory"]
        open_records = [record for record in joint["records"] if record["assigned_at"] < close_at]
        self.assertTrue(open_records)
        self.assertEqual(open_records, [record for record in full["records"]
                                        if record["assigned_at"] < close_at])
        self.assertEqual([path[:close_at + 1] for path in joint["paths"]],
                         [path[:close_at + 1] for path in full["paths"]])

    def test_reference_is_nonincreasing_and_cached_branches_are_counted(self):
        self.assertLessEqual(self.full["summary"]["F"], self.joint["summary"]["F"])
        log = [entry for entry in self.full["trajectory"]["search_log"] if entry["replanned"]]
        self.assertEqual(len(log), 5)
        self.assertAlmostEqual(log[0]["candidates"][0]["cost"], self.joint["summary"]["F"], places=12)
        for entry in log[1:]:
            self.assertLessEqual(entry["selected_cost"], entry["reference_cost"])
        self.assertAlmostEqual(log[-1]["selected_cost"], self.full["summary"]["F"], places=12)
        candidates = [candidate for entry in log for candidate in entry["candidates"]]
        self.assertEqual(sum(not candidate["cached"] for candidate in candidates), 7)
        self.assertTrue(any(candidate["cached"] for candidate in candidates))
        self.assertEqual(sum(entry["retained_incumbent"] for entry in log), 2)


if __name__ == "__main__":
    unittest.main()
