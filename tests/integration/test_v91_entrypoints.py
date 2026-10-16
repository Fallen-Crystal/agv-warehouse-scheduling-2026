import json
import tempfile
import unittest
from pathlib import Path

from agv.cli import main
from agv.evaluation.validation import validate
from agv.io.scenes import unpack_scene
from agv.web.app import calculate, calculate_loaded, validate_options


class CurrentEntrypointTests(unittest.TestCase):
    def test_cli_selects_stream_execution_without_a_time_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            self.assertEqual(
                main(
                    [
                        "run",
                        "--profile",
                        "v9.1",
                        "--tasks",
                        "2",
                        "--vehicles",
                        "1",
                        "--output",
                        str(path),
                    ]
                ),
                0,
            )
            archive = json.loads(path.read_text(encoding="utf-8"))
            s = unpack_scene(archive)
            self.assertTrue(s.is_v9_1)
            self.assertIsNone(s.horizon)
            self.assertTrue(validate(s, archive["result"]))
            self.assertEqual(archive["result"]["idle_policy"], "stream")

    def test_web_generates_and_reloads_completion_based_current_scene(self):
        options = validate_options(dict(profile="v9.1", task_count=1, vehicles=1))
        self.assertIsNone(options["horizon"])
        self.assertEqual(options["algorithm"], "sipp_stream_dispatch")
        entry = calculate(options)
        loaded = calculate_loaded(dict(format="agv-scene-v9.1", **entry))
        self.assertEqual(entry["scenario_sha256"], loaded["scenario_sha256"])
        self.assertTrue(loaded["result"]["feasible"])


if __name__ == "__main__":
    unittest.main()
