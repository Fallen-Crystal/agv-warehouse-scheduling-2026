"""Regression tests for the bounded first-batch rollout."""
import copy
import unittest
from model import example
from optimized import run
from initial_planning import choose_initial
from environment import Environment
from validation import validate


class InitialRolloutTests(unittest.TestCase):
    def test_rollout_is_feasible_and_no_worse_than_greedy(self):
        scenario = example(seed=2, layout='wide')
        baseline = run(scenario, assignment='greedy', joint=True)
        rolled = run(scenario, assignment='greedy', joint=True, initial_rollout=True)
        validate(scenario, rolled)
        self.assertTrue(rolled['feasible'])
        self.assertLessEqual(rolled['mean_flow_time'], baseline['mean_flow_time'])

    def test_rollout_uses_only_released_tasks(self):
        full = example(mode='dynamic', arrival='batch', task_count=12, vehicles=4)
        visible = copy.deepcopy(full)
        visible.tasks = [j for j in visible.tasks if j.release == 0]
        self.assertEqual(choose_initial(full), [])
        self.assertEqual(Environment(full).observe()['pending'],
                         Environment(visible).observe()['pending'])


if __name__ == '__main__':
    unittest.main()
