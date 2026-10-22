import itertools
import unittest
from dataclasses import replace

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.planning.f_search import ProposalCosts, match_batch, proposal_search
from agv.policy.f_portfolio import PortfolioSearch
from agv.policy.f_search import ObjectiveSearch
from agv.runner.environment import Environment
from agv.runner.f_research import run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


class FSearchTests(unittest.TestCase):
    def test_matching_agrees_with_exhaustive_full_batch(self):
        vehicles = [dict(id=k) for k in range(3)]
        jobs = [dict(id=k) for k in range(2)]
        costs = [[5, 2], [1, 9], [3, 4]]
        pairs = match_batch(vehicles, jobs, lambda v, j: costs[v["id"]][j["id"]])
        actual = sum(costs[v][j] for v, j in pairs)
        exact = min(
            sum(costs[v][j] for j, v in enumerate(p)) for p in itertools.permutations(range(3), 2)
        )
        self.assertEqual(actual, exact)
        self.assertEqual(len({v for v, j in pairs}), 2)

    def test_proposal_masks_do_not_change_final_weights_or_legality(self):
        s = generate_current(seed=90, vehicles=2, task_count=3, mode="static", horizon=None)
        for mask in ("T", "R", "D", "TR", "TD", "RD", "TRD"):
            r = score_result(s, run(s, terms=mask, budget=32))
            self.assertTrue(validate(s, r))
            self.assertEqual(r["objective_weights"], dict(time=0.5, response=0.3, distance=0.2))
            expected = (
                0.5 * r["normalized_time"]
                + 0.3 * r["normalized_response"]
                + 0.2 * r["normalized_distance"]
            )
            self.assertAlmostEqual(r["weighted_score"], expected)

    def test_budget_and_permutations(self):
        s = generate_current(seed=90, vehicles=2, task_count=5, mode="static", horizon=None)
        o = Environment(s, router_kind="sipp").observe()
        costs = ProposalCosts(o, Scenario.from_observation_map(o["map"], o["horizon"]))
        for method in ("ga", "random", "hybrid"):
            orders, stats = proposal_search(costs, method=method, budget=32, seed=9)
            self.assertLessEqual(stats["unique_evaluations"], 32)
            self.assertTrue(orders)
            for order in orders:
                self.assertEqual(set(order), set(costs.jobs))

    def test_hidden_future_invariance(self):
        a = generate_current(seed=91, vehicles=2, task_count=3, mode="static", horizon=None)
        a.tasks = [replace(j, release=0 if j.id == 0 else 50) for j in a.tasks]
        a.order_stream_end = 60
        b = Scenario.from_dict(a.to_dict())
        b.tasks = [j if j.id == 0 else replace(j, release=500, id=j.id + 100) for j in b.tasks]
        b.order_stream_end = 900
        oa, ob = (Environment(s, router_kind="sipp").observe() for s in (a, b))
        self.assertEqual(oa, ob)
        pa, pb = (ObjectiveSearch(world_factory=Environment, budget=32) for _ in range(2))
        self.assertEqual(pa.action(oa), pb.action(ob))
        self.assertEqual(pa.decisions, pb.decisions)

    def test_portfolio_contains_v1_and_keeps_execution_valid(self):
        s = generate_current(seed=94, vehicles=2, task_count=4, mode="static", horizon=None)
        r = score_result(s, run(s, method="portfolio"))
        self.assertTrue(validate(s, r))
        groups = {c["group"] for d in r["f_search"]["decisions"] for c in d["candidates"]}
        self.assertIn("v1", groups)
        self.assertTrue(groups & {"TR", "RD"})

    def test_portfolio_hidden_future_invariance(self):
        a = generate_current(seed=91, vehicles=2, task_count=3, mode="static", horizon=None)
        a.tasks = [replace(j, release=0 if j.id == 0 else 50) for j in a.tasks]
        a.order_stream_end = 60
        b = Scenario.from_dict(a.to_dict())
        b.tasks = [j if j.id == 0 else replace(j, release=500, id=j.id + 100) for j in b.tasks]
        b.order_stream_end = 900
        oa, ob = (Environment(s, router_kind="sipp").observe() for s in (a, b))
        pa, pb = (PortfolioSearch(world_factory=Environment) for _ in range(2))
        self.assertEqual(pa.action(oa), pb.action(ob))
        self.assertEqual(pa.decisions, pb.decisions)


if __name__ == "__main__":
    unittest.main()
