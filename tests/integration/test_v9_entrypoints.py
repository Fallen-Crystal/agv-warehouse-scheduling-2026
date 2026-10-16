import json
import tempfile
import unittest
from pathlib import Path

from agv.cli import main
from agv.evaluation.validation import validate
from agv.io.scenes import unpack_scene
from agv.web.app import calculate, calculate_loaded, validate_options


class V9EntrypointTests(unittest.TestCase):
    def test_cli_defaults_v9_to_medium_and_recomputes_its_own_score(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "v9.json"
            main(
                [
                    "run",
                    "--profile",
                    "v9",
                    "--tasks",
                    "2",
                    "--vehicles",
                    "1",
                    "--algorithm",
                    "sipp_standby16_dispatch",
                    "--output",
                    str(path),
                ]
            )
            archive = json.loads(path.read_text(encoding="utf-8"))
            scene = unpack_scene(archive)
            self.assertTrue(scene.is_v9)
            self.assertEqual(scene.width, 46)
            self.assertEqual(archive["result"]["model_version"], "mixed-v9-reviewed-v1")
            self.assertTrue(archive["result"]["score_valid"])
            self.assertTrue(validate(scene, archive["result"]))

    def test_web_generation_export_and_reload_keep_v9_profile(self):
        entry = calculate(
            dict(profile="v9", task_count=1, vehicles=1, algorithm="sipp_greedy_dispatch")
        )
        loaded = calculate_loaded({"format": "agv-scene-v9", **entry})
        self.assertEqual(entry["scenario_sha256"], loaded["scenario_sha256"])
        self.assertTrue(loaded["result"]["feasible"])

    def test_options_do_not_silently_reinterpret_old_geometry_or_enable_standby(self):
        for options in (
            dict(profile="v9", size="small"),
            dict(profile="v9", shelf_layers=2),
            dict(profile="v9", obstacle_layout="none"),
            dict(profile="v4", algorithm="sipp_standby16_dispatch"),
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_options(options)


if __name__ == "__main__":
    unittest.main()
