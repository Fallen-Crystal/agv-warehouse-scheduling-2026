import unittest
from copy import deepcopy

from agv.dispatch.candidates import legalize, make_batches
from agv.dispatch.greedy import greedy_action
from agv.simulation import Environment
from agv.warehouse import generate


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(generate(seed=10, task_count=12, vehicles=4), router_kind="sipp")
        self.obs = self.env.observe()

    def test_deterministic_legal_unique_and_bounded(self):
        before = deepcopy(self.obs)
        a = make_batches(self.obs)
        self.assertEqual(a, make_batches(self.obs))
        self.assertEqual(self.obs, before)
        self.assertLessEqual(len(a), 6)
        self.assertEqual(len(a), len({b.pairs for b in a}))
        self.assertEqual(a[0].pairs, tuple(legalize(greedy_action(self.obs), self.obs)))
        for batch in a:
            other = Environment(self.env._scenario, router_kind="sipp")
            other.assign(batch.pairs)

    def test_filter_never_duplicates_resource_vehicle_or_job(self):
        legal = legalize(greedy_action(self.obs), self.obs)
        self.assertTrue(legal)
        bad = legal + [legal[0], (-1, 0), (False, legal[0][1]), (1, -1), "bad"]
        self.assertEqual(legalize(bad, self.obs), legal)
        self.assertEqual(legalize(None, self.obs), [])
        same = deepcopy(self.obs)
        j = deepcopy(same["pending"][0])
        j.update(id=9999, dispatchable=True)
        same["pending"].append(j)
        got = legalize([(0, j["id"]), (1, same["pending"][0]["id"])], same)
        self.assertEqual(got, [(0, 9999)])

    def test_order_ablation_preserves_pair_set(self):
        batches = make_batches(self.obs, mode="order")
        self.assertGreaterEqual(len(batches), 2)
        for b in batches:
            self.assertEqual(set(b.pairs), set(batches[0].pairs))
        self.assertNotEqual(batches[0].pairs, batches[1].pairs)

    def test_budget_zero_and_future_pending_guard(self):
        self.assertEqual(make_batches(self.obs, 0), [])
        future = deepcopy(self.obs)
        j = deepcopy(future["pending"][0])
        j.update(id=9999, release=999)
        future["pending"].append(j)
        self.assertEqual(legalize([(0, 9999)], future), [])
        with self.assertRaises(ValueError):
            make_batches(self.obs, -1)


if __name__ == "__main__":
    unittest.main()
