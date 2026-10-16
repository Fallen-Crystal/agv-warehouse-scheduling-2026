import json
import tempfile
import unittest
from pathlib import Path

from agv.cli import main
from agv.evaluation.validation import validate
from agv.io.scenes import unpack_scene
from agv.web.app import calculate


class BCRDEntrypointTests(unittest.TestCase):
    def test_cli_saves_audited_bcrd_results(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "bcrd.json"
            self.assertEqual(
                main(
                    [
                        "run",
                        "--profile",
                        "v4",
                        "--tasks",
                        "8",
                        "--vehicles",
                        "2",
                        "--algorithm",
                        "bcrd_budget",
                        "--output",
                        str(path),
                    ]
                ),
                0,
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            scene = unpack_scene(raw)
            validate(scene, raw["result"])
            self.assertTrue(raw["result"]["feasible"])
            self.assertEqual(raw["result"]["algorithm"]["router"], "sipp")
            self.assertFalse(raw["result"]["algorithm"]["joint"])
            self.assertIn("dispatch_decisions", raw["result"])

    def test_http_service_accepts_new_policy(self):
        result = calculate(dict(profile="v4", algorithm="bcrd_budget", task_count=8, vehicles=2))
        self.assertEqual(result["result"]["completed"], 8)
        self.assertTrue(result["result"]["score_valid"])


if __name__ == "__main__":
    unittest.main()
