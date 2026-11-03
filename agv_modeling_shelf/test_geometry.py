"""Regression tests for the shared immutable map geometry cache."""
import unittest
from environment import Environment
from model import example
from geometry import from_observation


class GeometryCacheTests(unittest.TestCase):
    def test_same_map_reuses_one_router(self):
        scenario = example(mode='dynamic', arrival='burst', size='medium',
                           vehicles=6, task_count=30, seed=0)
        observation = Environment(scenario).observe()
        scenario_a, router_a = from_observation(observation)
        scenario_b, router_b = from_observation(observation)
        self.assertIs(scenario_a, scenario_b)
        self.assertIs(router_a, router_b)
        self.assertEqual(router_a.distance(scenario.homes[0], scenario.homes[0], 0), 0)

    def test_different_homes_do_not_share_router(self):
        a = example(size='small', vehicles=4, seed=0)
        b = example(size='small', vehicles=6, seed=0)
        _, router_a = from_observation(Environment(a).observe())
        _, router_b = from_observation(Environment(b).observe())
        self.assertIsNot(router_a, router_b)


if __name__ == '__main__':
    unittest.main()
