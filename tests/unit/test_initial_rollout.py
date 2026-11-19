"""Regression tests for the bounded static first-batch rollout planner."""

import copy
import unittest

from agv.api import calculate
from agv.dispatch.initial_batch import choose_initial
from agv.dispatch.optimized import run
from agv.dispatch.registry import run_named
from agv.domain import example
from agv.evaluation.validation import validate
from agv.simulation import Environment


class InitialRolloutTests(unittest.TestCase):
    def test_rollout_is_feasible_and_no_worse_than_greedy(self):
        scenario = example(seed=2, layout="wide")
        baseline = run(scenario, assignment="greedy", joint=True)
        rolled = run_named("joint_batch", scenario)
        validate(scenario, rolled)
        self.assertTrue(rolled["feasible"])
        self.assertTrue(rolled["algorithm"]["initial_rollout"])
        self.assertLessEqual(rolled["mean_flow_time"], baseline["mean_flow_time"])

    def test_rollout_uses_only_released_tasks_and_api_works(self):
        full = example(mode="dynamic", arrival="batch", task_count=12, vehicles=4)
        visible = copy.deepcopy(full)
        visible.tasks = [j for j in visible.tasks if j.release == 0]
        self.assertEqual(choose_initial(full), [])
        self.assertEqual(
            Environment(full).observe()["pending"],
            Environment(visible).observe()["pending"],
        )
        entry = calculate({"profile": "legacy", "mode": "static", "algorithm": "joint_batch"})
        self.assertTrue(entry["result"]["feasible"])


if __name__ == "__main__":
    unittest.main()
