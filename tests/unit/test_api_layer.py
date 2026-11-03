"""The application service layer is usable without the HTTP boundary."""

import unittest

from agv import api
from agv.web import app as web_app


class ApiLayerTests(unittest.TestCase):
    def test_api_owns_single_run_and_web_reexports_it(self):
        self.assertIs(api.calculate, web_app.calculate)
        self.assertIs(api.calculate_loaded, web_app.calculate_loaded)
        self.assertIs(api.calculate_batch, web_app.calculate_batch)
        entry = api.calculate({"task_count": 2, "vehicles": 1, "seed": 3})
        self.assertEqual(entry["scenario"]["tasks"][0]["id"], 0)
        self.assertTrue(entry["result"]["feasible"])

    def test_scene_builder_does_not_require_http(self):
        options = api.validate_options({"profile": "v4", "task_count": 2, "vehicles": 2})
        scenario = api.build_scene(options)
        self.assertTrue(scenario.is_v4)

    def test_scene_factory_matches_profile_generators(self):
        from agv.domain import example
        from agv.warehouse.layout import generate as generate_v4
        from agv.warehouse.mixed import generate_current as generate_v91

        self.assertEqual(
            api.generate_scene(profile="legacy", task_count=2, seed=1).to_dict(),
            example(task_count=2, seed=1).to_dict(),
        )
        self.assertEqual(
            api.generate_scene(profile="v4", task_count=2, vehicles=2, seed=1).to_dict(),
            generate_v4(task_count=2, vehicles=2, seed=1).to_dict(),
        )
        self.assertEqual(
            api.generate_scene(profile="v9.1", task_count=2, vehicles=1, seed=1).to_dict(),
            generate_v91(task_count=2, vehicles=1, seed=1).to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
