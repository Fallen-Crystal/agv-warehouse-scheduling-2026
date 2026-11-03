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


if __name__ == "__main__":
    unittest.main()
