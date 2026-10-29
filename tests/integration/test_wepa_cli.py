"""Installed CLI settings must not silently alter or ignore pinned real windows."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WepaCliTests(unittest.TestCase):
    def test_zero_fixed_delay_and_rejected_generator_options(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [
                sys.executable,
                "-m",
                "agv",
                "run",
                "--profile",
                "wepa",
                "--algorithm",
                "hungarian",
                "--latency",
                "fixed",
                "--output",
                "out.json",
            ]
            result = subprocess.run(command, cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            trace = json.loads((Path(directory) / "out.json").read_text(encoding="utf-8"))
            self.assertTrue(trace["row"]["valid"])
            for option, value in (("--vehicles", "8"), ("--tasks", "2"), ("--layers", "3")):
                result = subprocess.run(
                    command[:-1] + ["bad.json", option, value],
                    cwd=directory,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("fixes source arrivals", result.stderr)
            self.assertFalse((Path(directory) / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()
