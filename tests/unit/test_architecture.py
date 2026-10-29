"""The architecture gate fails on real dependency/ownership regressions."""

import tempfile
import unittest
from pathlib import Path

from scripts.check_architecture import check_architecture


class ArchitectureGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write(
            "world/state.py",
            "class WorldState:\n"
            "    def tick(self): pass\n"
            "    def assign(self): pass\n"
            "    def result(self): pass\n",
        )
        self.write("world/reservations.py", "class ReservationTable: pass\n")
        self.write("runner/run.py", "def run():\n    while False: pass\n")

    def write(self, relative, source):
        path = self.root / "src" / "agv" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def codes(self):
        return {violation.code for violation in check_architecture(self.root)}

    def test_valid_small_architecture_passes(self):
        self.write("core/__init__.py", "from agv.core.model import Task\n")
        self.write("world/commands.py", "from agv.rules import Ruleset\n")
        self.write("policy/controller.py", "from agv.planning import create_router\n")
        self.assertEqual(check_architecture(self.root), [])

    def test_imports_inside_functions_and_dynamic_imports_are_checked(self):
        self.write(
            "world/broken.py",
            "def build():\n    from agv.policy import controller\n    __import__('agv.runner')\n",
        )
        violations = check_architecture(self.root)
        self.assertEqual([v.code for v in violations], ["dependency", "dependency"])
        self.assertEqual([v.line for v in violations], [2, 3])

    def test_compatibility_callers_are_allowed_but_production_reverse_imports_are_not(self):
        self.write("dispatch/greedy.py", "from agv.runner import run\n")
        self.assertEqual(self.codes(), set())
        self.write("policy/greedy.py", "from agv.dispatch.greedy import run\n")
        self.assertIn("compat-import", self.codes())

    def test_validator_cannot_depend_on_runtime_even_through_local_import(self):
        self.write(
            "evaluation/validation.py",
            "def validate():\n    from agv.world.state import WorldState\n",
        )
        self.assertIn("validator-independence", self.codes())

    def test_wepa_and_package_validators_keep_the_independent_boundary(self):
        for module in ("evaluation/wepa.py", "evaluation/validation/wepa.py"):
            with self.subTest(module=module):
                self.write(
                    module,
                    "def validate():\n    from agv.planning.sipp import SafeIntervalRouter\n",
                )
                self.assertIn("validator-independence", self.codes())

    def test_production_cannot_import_archive_top_level_modules(self):
        self.write(
            "policy/wepa/broken.py",
            "from improved.forecast import rollout\n"
            "def build():\n    from wepa.kernel import World\n",
        )
        violations = check_architecture(self.root)
        self.assertEqual([v.code for v in violations], ["research-namespace", "research-namespace"])
        self.assertEqual([v.line for v in violations], [1, 3])

    def test_ranker_accepts_pure_core_helpers_but_rejects_runtime_dependencies(self):
        self.write("learning/ranker.py", "from agv.core.features import features\n")
        self.assertEqual(self.codes(), set())
        self.write("learning/ranker.py", "from agv.world.state import WorldState\n")
        self.assertIn("ranker-independence", self.codes())

    def test_private_state_assignment_subscript_and_mutators_are_rejected(self):
        self.write(
            "policy/broken.py",
            "def change(env):\n"
            "    env._plans = []\n"
            "    env._records[0]['return_end'] = 1\n"
            "    env._active.append(1)\n"
            "    setattr(env, '_paths', [])\n",
        )
        violations = check_architecture(self.root)
        self.assertEqual(len(violations), 4)
        self.assertEqual({v.code for v in violations}, {"state-ownership"})
        self.assertEqual({v.line for v in violations}, {2, 3, 4, 5})

    def test_legacy_run_loop_and_second_kernel_are_rejected(self):
        self.write("dispatch/bcrd.py", "def run():\n    while True: pass\n")
        self.assertIn("duplicate-runner", self.codes())
        self.write(
            "policy/forecast.py",
            "class OtherKernel:\n"
            "    def tick(self): pass\n"
            "    def assign(self): pass\n"
            "    def result(self): pass\n",
        )
        self.assertIn("kernel-count", self.codes())

    def test_second_reservation_implementation_is_rejected(self):
        self.write("planning/reservations.py", "class PlanReservations: pass\n")
        self.assertTrue({"reservation-count", "reservation-ownership"} <= self.codes())

    def test_repository_obeys_dependency_and_ownership_contracts(self):
        repository = Path(__file__).resolve().parents[2]
        self.assertEqual(check_architecture(repository), [])


if __name__ == "__main__":
    unittest.main()
