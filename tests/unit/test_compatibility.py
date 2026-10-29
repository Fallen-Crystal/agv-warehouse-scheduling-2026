"""Historical imports remain usable while current entry points stay warning-free."""

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class CompatibilityTests(unittest.TestCase):
    def isolated(self, source):
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )

    def test_deprecated_roots_preserve_exports_and_emit_migration_guidance(self):
        process = self.isolated("""
            import warnings
            with warnings.catch_warnings(record=True) as notices:
                warnings.simplefilter("always", DeprecationWarning)
                import agv.dispatch
                import agv.domain
                import agv.simulation
                import agv.wepa
            from agv.core import Task
            from agv.warehouse.scenarios import Scenario
            from agv.runner.environment import Environment
            assert agv.domain.Task is Task
            assert agv.domain.Scenario is Scenario
            assert agv.simulation.Environment is Environment
            assert callable(agv.wepa.main)
            messages = [str(w.message) for w in notices if w.category is DeprecationWarning]
            assert len(messages) == 4, messages
            assert all("deprecated" in message for message in messages)
            assert any("agv run --profile wepa" in message for message in messages)
        """)
        self.assertEqual(process.stderr, "")

    def test_gate_does_not_import_historical_search_or_deprecated_shims(self):
        self.isolated("""
            import sys, warnings
            warnings.simplefilter("error", DeprecationWarning)
            from agv.runner.wepa import run
            from tests.unit.test_wepa_ported_variants import model
            result = run(model(), "gate", seed=3)
            assert result["valid"]
            assert not any(name.startswith("agv.policy.wepa.legacy") for name in sys.modules)
            assert "agv.policy.wepa.base_policy" not in sys.modules
        """)

    def test_explicit_simple_arm_loads_historical_implementation_without_warning(self):
        self.isolated("""
            import sys, warnings
            warnings.simplefilter("error", DeprecationWarning)
            from agv.runner.wepa import run
            from tests.unit.test_wepa_ported_variants import model
            result = run(model(), "simple", seed=3)
            assert result["valid"]
            assert "agv.policy.wepa.legacy.policy" in sys.modules
            assert "agv.policy.wepa.base_policy" not in sys.modules
        """)

    def test_old_base_imports_are_thin_warned_aliases(self):
        self.isolated("""
            import warnings
            with warnings.catch_warnings(record=True) as notices:
                warnings.simplefilter("always", DeprecationWarning)
                from agv.policy.wepa.base_policy import LinearPolicy
                from agv.policy.wepa.base_forecast import rollout
                from agv.policy.wepa.base_genetic import candidates
                from agv.policy.wepa.legacy_proxy import MixedCosts
            from agv.policy.wepa.legacy.policy import LinearPolicy as ActualPolicy
            from agv.policy.wepa.legacy.forecast import rollout as actual_rollout
            from agv.policy.wepa.legacy.genetic import candidates as actual_candidates
            from agv.policy.wepa.legacy.proxy import MixedCosts as ActualCosts
            assert LinearPolicy is ActualPolicy
            assert rollout is actual_rollout
            assert candidates is actual_candidates
            assert MixedCosts is ActualCosts
            assert len(notices) == 4
        """)

    def test_normal_cli_runs_with_deprecation_warnings_treated_as_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            process = subprocess.run(
                [
                    sys.executable,
                    "-Werror::DeprecationWarning",
                    "-m",
                    "agv",
                    "run",
                    "--profile",
                    "wepa",
                    "--case",
                    "wepa-day45-bin4335",
                    "--algorithm",
                    "hungarian",
                    "--output",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["row"]["valid"])
            self.assertNotIn("DeprecationWarning", process.stderr)

    def test_legacy_wepa_launcher_still_executes_its_real_entry_point(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            process = subprocess.run(
                [
                    sys.executable,
                    "-Walways::DeprecationWarning",
                    "-m",
                    "agv.wepa",
                    "--case",
                    "wepa-day45-bin4335",
                    "--profile",
                    "hungarian",
                    "--output",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["row"]["valid"])
            self.assertIn("agv.wepa is a deprecated launcher", process.stderr)


if __name__ == "__main__":
    unittest.main()
