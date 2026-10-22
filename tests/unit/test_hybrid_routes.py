import random
import unittest

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.planning.hybrid_routes import HybridRouter
from agv.planning.sipp import SafeIntervalRouter
from agv.runner.f_research import run as run_portfolio
from agv.runner.path_research import ROUTES, path_world_type, run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario
from tests.unit.test_sipp import check_leg


class HybridPathTests(unittest.TestCase):
    def test_factory_exposes_counters_without_live_router_or_future_scene(self):
        s = generate_current(seed=2205, vehicles=2, task_count=3, mode="dynamic", horizon=None)
        factory = path_world_type("aco_sipp")
        factory(s)
        self.assertFalse(hasattr(factory, "actual"))
        self.assertTrue(all(type(value) is int for value in factory.actual_diagnostics.values()))

    def test_random_reservations_keep_service_vertex_and_edge_safety(self):
        rng = random.Random(26022)
        s = Scenario(5, 5, {(2, 2)}, set(), [(0, 0)], [], 24).check()
        cells = [(x, y) for x in range(5) for y in range(5) if s.free((x, y))]
        changes = 0
        for case in range(32):
            start, goal = rng.sample(cells, 2)
            vertices = {(rng.randrange(25), rng.choice(cells)) for _ in range(40)}
            edges = {(rng.randrange(20), (1, 0), (0, 0))}
            blocked, service = {2, 5}, 2
            for timing, base in (("astar", Router), ("sipp", SafeIntervalRouter)):
                expected = base(s).leg(
                    start, goal, 0, 0, vertices, edges, service, service_blocked=blocked
                )
                for method in ("aco", "pso"):
                    r = HybridRouter(s, method=method, timing=timing, seed=case)
                    path = r.leg(
                        start, goal, 0, 0, vertices, edges, service, service_blocked=blocked
                    )
                    if expected is None:
                        self.assertIsNone(path)
                    else:
                        self.assertIsNotNone(path)
                        check_leg(self, path, s, start, goal, 0, vertices, edges, service)
                        begin = len(path) - 1 - service
                        self.assertTrue(
                            all(t not in blocked for t in range(begin, begin + service))
                        )
                    changes += r.diagnostics["changed"]
                    self.assertLessEqual(r.diagnostics["timed_candidates"], 4)
        self.assertGreater(changes, 0, "Hybrid must be capable of changing actual routes")

    def test_no_reservations_keeps_incumbent_and_zero_budget_falls_back(self):
        s = Scenario(4, 4, set(), set(), [(0, 0)], [], 24).check()
        for method in ("aco", "pso"):
            baseline = SafeIntervalRouter(s).leg((0, 0), (3, 3), 0, 0, set(), set())
            r = HybridRouter(s, method=method)
            self.assertEqual(r.leg((0, 0), (3, 3), 0, 0, set(), set()), baseline)
            self.assertEqual(r.diagnostics["timed_candidates"], 0)
            r = HybridRouter(s, method=method, candidate_budget=0)
            self.assertEqual(r.leg((0, 0), (3, 3), 0, 0, set(), set()), baseline)

    def test_all_path_modes_finish_valid_warehouse_execution(self):
        s = generate_current(seed=2201, vehicles=2, task_count=3, mode="static", horizon=None)
        for route in ROUTES:
            result = score_result(s, run(s, route=route, orders="greedy"))
            validate(s, result)
            self.assertTrue(result["score_valid"], result.get("diagnostics"))

    def test_static_reservations_cannot_see_hidden_future_tasks(self):
        a = generate_current(seed=2202, vehicles=2, task_count=3, mode="static", horizon=None)
        b = Scenario.from_dict(a.to_dict())
        b.tasks = []
        start, goal = a.homes[0], a.tasks[0].pickup
        if goal is None:
            goal = a.pickup_candidates(a.tasks[0])[0]
        reservations = {(5, a.homes[1])}
        for method in ("aco", "pso"):
            x = HybridRouter(a, method=method).leg(start, goal, 0, 0, reservations, set())
            y = HybridRouter(b, method=method).leg(start, goal, 0, 0, reservations, set())
            self.assertEqual(x, y)

    def test_hybrid_router_is_identical_in_real_and_shadow_worlds(self):
        s = generate_current(seed=2203, vehicles=2, task_count=3, mode="static", horizon=None)
        for route in ("sipp", "aco_sipp", "pso_astar"):
            result = score_result(s, run(s, route=route, orders="assignment", candidate_budget=2))
            validate(s, result)
            self.assertTrue(result["score_valid"], result.get("diagnostics"))
            self.assertTrue(result["path_research"]["commit_feedback"])
            self.assertFalse(
                any(x["prediction_mismatch"] for x in result["path_research"]["commit_feedback"])
            )

    def test_sipp_injection_preserves_existing_portfolio_trajectory(self):
        s = generate_current(seed=2204, vehicles=2, task_count=3, mode="static", horizon=None)
        old = run_portfolio(s, method="portfolio")
        new = run(s, route="sipp", orders="portfolio")
        for key in ("paths", "events", "assignments", "moves", "makespan", "time"):
            self.assertEqual(old[key], new[key], key)


if __name__ == "__main__":
    unittest.main()
