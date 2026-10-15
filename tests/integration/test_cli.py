import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_installed_module_runs_outside_source_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            command = [
                sys.executable,
                "-m",
                "agv",
                "run",
                "--tasks",
                "2",
                "--algorithm",
                "sipp_learned",
                "--output",
                "result.json",
            ]
            first = subprocess.run(command, cwd=folder, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = json.loads((Path(folder) / "result.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["result"]["feasible"])
            second = subprocess.run(command, cwd=folder, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(
                json.loads((Path(folder) / "result.json").read_text(encoding="utf-8")), saved
            )

    def test_cli_bad_arguments_return_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            p = subprocess.run(
                [sys.executable, "-m", "agv", "run", "--seed", "-1", "--output", "x.json"],
                cwd=folder,
                capture_output=True,
                text=True,
            )
            self.assertEqual(p.returncode, 2)
            self.assertFalse((Path(folder) / "x.json").exists())
