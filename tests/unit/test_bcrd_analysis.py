"""Accounting checks do not substitute for independent execution validation."""

import copy
import unittest

from agv.dispatch.optimized import run
from agv.evaluation.dispatch_analysis import analyze_dispatch
from agv.evaluation.validation import validate
from agv.warehouse.layout import generate


class DispatchLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = generate(task_count=4, vehicles=2, seed=10, horizon=None)
        cls.result = run(cls.scene, assignment="greedy", router_kind="sipp", joint=False)
        validate(cls.scene, cls.result)

    def test_exact_timestamp_and_path_accounting(self):
        audit = analyze_dispatch(self.scene, self.result)
        self.assertTrue(audit["execution_successful"])
        self.assertTrue(audit["all_ledgers_reconcile"])
        self.assertEqual(audit["means"]["flow_time"], self.result["mean_flow_time"])
        for row in audit["tasks"]:
            self.assertEqual(row["ledger_total"], row["flow_time"])
            self.assertEqual(
                row["empty_travel_moves"] + row["empty_stationary_wait"], row["pickup_duration"]
            )
            self.assertEqual(
                row["loaded_travel_moves"] + row["loaded_stationary_wait"], row["loaded_duration"]
            )
        self.assertEqual(sum(v["moves"] for v in audit["fleet"]), self.result["moves"])
        self.assertEqual(
            sum(v["service_steps"] for v in audit["fleet"]), self.result["service_steps"]
        )

    def test_read_only(self):
        before = copy.deepcopy(self.result)
        scene = self.scene.to_dict()
        analyze_dispatch(self.scene, self.result)
        self.assertEqual(self.result, before)
        self.assertEqual(self.scene.to_dict(), scene)

    def test_reject_corrupt_service_and_timestamp(self):
        for field, value in (("pickup_end", -1), ("delivery_arrival", 0)):
            bad = copy.deepcopy(self.result)
            bad["events"][0][field] = value
            with self.assertRaises(ValueError):
                analyze_dispatch(self.scene, bad)

    def test_failed_execution_retains_incomplete_label(self):
        bad = copy.deepcopy(self.result)
        bad["feasible"] = False
        audit = analyze_dispatch(self.scene, bad)
        self.assertFalse(audit["execution_successful"])
        self.assertEqual(audit["ledger_scope"], "completed_tasks_only")
        self.assertIn("unidentified", audit["dispatch_wait_attribution"])


if __name__ == "__main__":
    unittest.main()
