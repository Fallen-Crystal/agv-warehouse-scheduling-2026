import itertools
import math
import random
import unittest
from copy import deepcopy

from agv.core.objectives import LinearObjective
from agv.evaluation.objectives.linear_f import checked_score
from agv.policy.wepa.forecast import rollout, snapshot
from agv.policy.wepa.hungarian import linear_batch, minimum_assignment
from agv.policy.wepa.hungarian_seed import seeds
from agv.policy.wepa.policy import plan_from_prediction
from agv.policy.wepa.proxy import MixedCosts
from agv.runner.wepa import run
from tests.exact.fixtures import make
from tests.exact.fixtures import new_world as World


def enumerate_pairs(rows, cols):
    for n in range(min(rows, cols) + 1):
        for indices in itertools.combinations(range(rows), n):
            for chosen in itertools.permutations(range(cols), n):
                yield list(zip(indices, chosen))


class HungarianTests(unittest.TestCase):
    def test_rectangular_forbidden_and_negative_costs_against_exhaustive(self):
        rng = random.Random(59)
        for n in range(1, 5):
            for m in range(5):
                for trial in range(6):
                    matrix = [
                        [
                            rng.randrange(-10, 20) if rng.random() > 0.3 else math.inf
                            for _ in range(m)
                        ]
                        for _ in range(n)
                    ]
                    options = [
                        pairs
                        for pairs in enumerate_pairs(n, m)
                        if all(math.isfinite(matrix[i][j]) for i, j in pairs)
                    ]
                    target = min((-len(p), sum(matrix[i][j] for i, j in p)) for p in options)
                    pairs = minimum_assignment(matrix)
                    self.assertEqual((-len(pairs), sum(matrix[i][j] for i, j in pairs)), target)

    def test_additive_assignment_matches_old_exact_dp(self):
        from agv.policy.wepa.matching import match_batch

        rng = random.Random(19)
        for _ in range(40):
            matrix = [[rng.randrange(0, 30) for _ in range(8)] for _ in range(6)]
            a = minimum_assignment(matrix)
            b = match_batch(
                [dict(id=k) for k in range(6)],
                [dict(id=j) for j in range(8)],
                lambda v, j: matrix[v["id"]][j["id"]],
            )
            self.assertEqual(sum(matrix[k][j] for k, j in a), sum(matrix[k][j] for k, j in b))

    def test_F_surrogate_threshold_matching_against_exhaustive(self):
        rng = random.Random(61)
        obj = LinearObjective(vehicles=3)
        for n in range(1, 4):
            for m in range(1, 5):
                for _ in range(4):
                    edges = {
                        (i, j): (rng.randrange(1, 40), rng.randrange(1, 35))
                        for i in range(n)
                        for j in range(m)
                    }
                    fixed = rng.randrange(10, 55)
                    now = 8
                    wr = obj.weights[1] / obj.scales[1] / 17

                    def cost(p):
                        return obj.weights[0] / obj.scales[0] * max(
                            [fixed] + [now + edges[i, j][0] for i, j in p]
                        ) + sum(
                            wr * edges[i, j][0] + obj.weights[2] / obj.scales[2] * edges[i, j][1]
                            for i, j in p
                        )

                    pairs, meta = linear_batch(
                        list(range(n)), list(range(m)), edges, obj, now, fixed, 17
                    )
                    target = min(cost(p) for p in enumerate_pairs(n, m) if len(p) == min(n, m))
                    self.assertAlmostEqual(cost(pairs), target, places=12)

    def test_seeds_are_complete_deterministic_and_do_not_change_physics(self):
        w = World(make("layers"))
        w.publish_and_complete()
        v = snapshot(w)
        prediction, _ = rollout(v)
        order, owners = plan_from_prediction(prediction, set(v.tasks) - v.assigned)
        physical = deepcopy((v.stock, v.bound, v.plans, v.records, v.active, v.assigned, v.locks))
        a, meta = seeds(MixedCosts(v, prediction), order, owners, LinearObjective(vehicles=2))
        b, _ = seeds(MixedCosts(v, prediction), order, owners, LinearObjective(vehicles=2))
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), 2)
        self.assertTrue(all(x["complete"] for x in meta["variants"]))
        self.assertEqual(
            physical, (v.stock, v.bound, v.plans, v.records, v.active, v.assigned, v.locks)
        )
        for o, x, kind in a:
            self.assertEqual(sorted(o), sorted(order))
            self.assertEqual(set(x), set(order))
            self.assertTrue(all(0 <= k < 2 for k in x.values()))

    def test_all_three_arms_have_independently_valid_traces(self):
        for name in ("cross_out", "mixed", "layers", "mixed_burst"):
            for arm in ("gate", "hungarian", "hga"):
                with self.subTest(name=name, arm=arm):
                    m = make(name)
                    obj = LinearObjective(vehicles=2)
                    r = run(m, arm, objective=obj)
                    self.assertTrue(checked_score(m, r, obj)["audit"]["valid"])
                    for log in r["search_log"]:
                        if "previews" in log:
                            self.assertLessEqual(log["previews"], 6)
                            self.assertLessEqual(log["proxy_evaluations"], 192)
                            self.assertLessEqual(log["score"], log["base_score"] + 1e-12)
                        if "hungarian_initialization" in log:
                            self.assertLessEqual(log["hungarian_initialization"]["generated"], 2)
                            self.assertEqual(log["hungarian_initialization"]["routing_previews"], 0)

    def test_new_methods_do_not_see_unpublished_requests(self):
        from tests.unit.test_wepa_ported_variants import model

        for arm in ("hungarian", "hga"):
            a, b = run(model(200), arm, seed=3), run(model(300), arm, seed=3)
            self.assertEqual(
                [d for d in a["decisions"] if d["time"] < 200],
                [d for d in b["decisions"] if d["time"] < 200],
            )

    def test_new_methods_replay_exactly(self):
        for arm in ("hungarian", "hga"):
            m = make("mixed_burst")
            obj = LinearObjective(vehicles=2)
            a, b = run(m, arm, seed=4, objective=obj), run(m, arm, seed=4, objective=obj)
            for key in ("paths", "labels", "records", "decisions", "search_log", "T", "R", "D"):
                self.assertEqual(a[key], b[key])

    def test_no_ga_calls_for_hungarian_and_seeded_GA_is_exercised(self):
        m = make("mixed_burst")
        obj = LinearObjective(vehicles=2)
        h = run(m, "hungarian", objective=obj)
        g = run(m, "hga", objective=obj)
        self.assertTrue(h["search_log"])
        self.assertTrue(all(l["mode"] == "rolling_hungarian" for l in h["search_log"]))
        logs = [l for l in g["search_log"] if "hungarian_initialization" in l]
        self.assertTrue(logs)
        self.assertTrue(any(l["hungarian_initialization"]["generated"] > 0 for l in logs))


if __name__ == "__main__":
    unittest.main()
