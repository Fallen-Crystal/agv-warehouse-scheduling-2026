import tempfile
import unittest
from pathlib import Path

from agv.experiments.bcrd import _run, validate_protocol
from scripts.verify_bcrd import verify


class V9ExperimentTests(unittest.TestCase):
    def protocol(self):
        return dict(
            schema="agv-bcrd-protocol-v1",
            profile="v9",
            split="development",
            frozen=False,
            seeds=[10],
            configs={"empty": dict(task_count=0, vehicles=1)},
            solvers={"G0": dict(policy="greedy"), "wait": dict(policy="greedy", idle_hold_steps=2)},
            baseline="G0",
        )

    def test_new_profile_matrix_preserves_fixed_source_and_independent_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result"
            _run(output, self.protocol())
            audit = verify(output)
            self.assertEqual(audit["rows"], 2)
            self.assertEqual(audit["independent_traces_validated"], 2)

    def test_standby_cannot_be_hidden_inside_old_profile_or_bcrd(self):
        for profile, policy in (("v4", "greedy"), ("v9", "bcrd")):
            p = self.protocol()
            p["profile"] = profile
            p["solvers"]["wait"]["policy"] = policy
            with self.subTest(profile=profile, policy=policy), self.assertRaises(ValueError):
                validate_protocol(p)


if __name__ == "__main__":
    unittest.main()
