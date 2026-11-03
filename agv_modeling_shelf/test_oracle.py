"""Small-instance exact-oracle regression tests."""
import unittest
from baseline import run as baseline_run
from model import example
from oracle import exact_static
from validation import validate


class OracleTests(unittest.TestCase):
    def test_oracle_is_feasible_and_no_worse_than_greedy(self):
        for seed in range(3):
            scenario = example(task_count=4, vehicles=2, seed=seed)
            result = exact_static(scenario)
            validate(scenario, result)
            self.assertTrue(result['feasible'])
            self.assertEqual(len(result['events']), 4)
            self.assertLessEqual(result['mean_flow_time'],
                                 baseline_run(scenario)['mean_flow_time'])

    def test_oracle_rejects_dynamic_and_large(self):
        with self.assertRaises(ValueError):
            exact_static(example(mode='dynamic', task_count=4, vehicles=2))
        with self.assertRaises(ValueError):
            exact_static(example(task_count=6, vehicles=2))


if __name__ == '__main__':
    unittest.main()
