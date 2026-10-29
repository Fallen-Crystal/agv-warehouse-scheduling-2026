import hashlib
import itertools
import json
import random
import unittest
from copy import deepcopy
from pathlib import Path

from agv.core.objectives import LinearObjective
from agv.data.wepa import build
from agv.evaluation.objectives.linear_f import checked_score
from agv.policy.wepa.matching import linear_assignment
from agv.policy.wepa.profiles import PROFILES
from agv.runner.wepa import run


def model(release=100):
    jobs = [
        dict(
            id=i,
            source_row=i,
            kind="retrieval" if i < 4 else "delivery",
            sku=10,
            release=0 if i < 4 else release,
            source_time=0,
            source_dock=1,
            batch=i,
            week=1,
        )
        for i in range(5)
    ]
    return build(
        dict(case="variants-micro", initial={"10": 5}, close_at=release, tasks=jobs),
        size="medium",
        vehicles=2,
    )


class VariantTests(unittest.TestCase):
    def test_linear_batch_matching_agrees_with_exhaustive_assignments(self):
        rng = random.Random(29)
        for m in range(1, 5):
            for n in range(1, m + 1):
                for _ in range(8):
                    cars = [dict(id=k) for k in range(m)]
                    jobs = [dict(id=j, release=rng.randrange(5)) for j in range(n)]
                    edges = {
                        (k, j): (rng.randrange(5, 100), rng.randrange(1, 50))
                        for k in range(m)
                        for j in range(n)
                    }
                    obj = LinearObjective(vehicles=m)
                    wt, wr, wd = [w / s for w, s in zip(obj.weights, obj.scales)]

                    def value(pairs):
                        return wt * max([40] + [10 + edges[k, j][0] for k, j in pairs]) + sum(
                            wr * (10 + edges[k, j][0] - jobs[j]["release"]) / 20
                            + wd * edges[k, j][1]
                            for k, j in pairs
                        )

                    pairs = linear_assignment(cars, jobs, edges, obj, 10, 40, 20)
                    best = min(
                        value(list(zip(owners, range(n))))
                        for owners in itertools.permutations(range(m), n)
                    )
                    self.assertAlmostEqual(value(pairs), best, places=12)

    def test_every_profile_has_valid_physical_trace_and_fixed_objective(self):
        for name in PROFILES:
            with self.subTest(name=name):
                m = model()
                result = run(m, name, objective=LinearObjective(vehicles=2))
                self.assertTrue(
                    checked_score(m, result, LinearObjective(vehicles=2))["audit"]["valid"]
                )
                for log in result["search_log"]:
                    self.assertEqual(
                        log.get("objective_sha256"), LinearObjective(vehicles=2).fingerprint
                    )
                    if "previews" in log:
                        self.assertLessEqual(log["previews"], PROFILES[name]["previews"])
                        self.assertLessEqual(
                            log["proxy_evaluations"],
                            PROFILES[name]["proxy"] + PROFILES[name]["repair"],
                        )
                        self.assertLessEqual(log["score"], log["base_score"] + 1e-12)

    def test_gate_uses_published_state_only(self):
        a, b = model(200), model(300)
        for name in ("gate", "restored", "anchor", "guided", "guided_gate"):
            with self.subTest(name=name):
                x, y = run(a, name, seed=4), run(b, name, seed=4)
                self.assertEqual(
                    [d for d in x["decisions"] if d["time"] < 200],
                    [d for d in y["decisions"] if d["time"] < 200],
                )

    def test_baseline_repeat_is_exact(self):
        m = model()
        a, b = run(m, "simple", seed=3), run(m, "simple", seed=3)
        for key in ("paths", "records", "decisions", "search_log", "T", "R", "D"):
            self.assertEqual(a[key], b[key])

    def test_guided_guarded_profile_replays_exactly(self):
        m = model()
        a, b = run(m, "guided_gate", seed=3), run(m, "guided_gate", seed=3)
        for key in ("paths", "records", "decisions", "search_log", "T", "R", "D"):
            self.assertEqual(a[key], b[key])

    def test_rule_controls_independent_of_search_profiles(self):
        # Expected traces were produced by the archive's separate v2 runner.
        controls = json.loads(
            (Path(__file__).parents[1] / "golden/wepa/rule-controls.json").read_text(
                encoding="utf-8"
            )
        )
        for name in ("eta", "fcfs"):
            result = run(model(), name)
            for key in ("paths", "records", "decisions", "T", "R", "D"):
                raw = json.dumps(result[key], sort_keys=True, separators=(",", ":"))
                self.assertEqual(
                    hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    controls["cases"][name][key],
                    (name, key),
                )

    def test_checked_score_rejects_illegal_result(self):
        m = model()
        a = deepcopy(run(m, "wide"))
        a["D"] -= 1
        with self.assertRaises(ValueError):
            checked_score(m, a, LinearObjective(vehicles=2))


if __name__ == "__main__":
    unittest.main()
