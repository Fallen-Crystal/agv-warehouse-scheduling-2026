"""Immutable geometry and reference-router caches stay scoped and reusable."""

import unittest

from agv.domain import example
from agv.planning.geometry import from_observation, scenario_from_observation
from agv.simulation import Environment


class GeometryCacheTests(unittest.TestCase):
    def test_astar_geometry_is_reused(self):
        observation = Environment(example(task_count=4, vehicles=2)).observe()
        scenario_a, router_a = from_observation(observation)
        scenario_b, router_b = from_observation(observation)
        scenario_c = scenario_from_observation(observation)
        self.assertIs(scenario_a, scenario_b)
        self.assertIs(scenario_a, scenario_c)
        self.assertIs(router_a, router_b)
        self.assertEqual(router_a.distance(scenario_a.homes[0], scenario_a.homes[0], 0), 0)

    def test_sipp_router_is_not_shared(self):
        observation = Environment(example(task_count=4, vehicles=2)).observe()
        scenario_a, router_a = from_observation(observation, "sipp")
        scenario_b, router_b = from_observation(observation, "sipp")
        self.assertIs(scenario_a, scenario_b)
        self.assertIsNot(router_a, router_b)


if __name__ == "__main__":
    unittest.main()
