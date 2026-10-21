import itertools
import unittest
from dataclasses import replace

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.planning.order_search import OrderCosts, exact_single
from agv.policy.forecast import ShadowState, _task
from agv.policy.research_search import PriorityDriver, SearchPolicy
from agv.runner.environment import Environment
from agv.runner.research import run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


class ExactReferenceTests(unittest.TestCase):
    def test_pure_priority_event_skips_match_every_step_forecast(self):
        s = generate_current(
            seed=61, task_count=3, vehicles=2, mode="static", shelf_layers=8, horizon=None
        )
        base = next(j for j in s.tasks if j.shelf_level > 1)
        s.tasks = [
            replace(base, id=i, shelf_level=l, pickup_service=2 * l)
            for i, l in enumerate((8, 5, 2))
        ]
        s.check()
        obs = Environment(s, router_kind="sipp").observe()
        geometry = Scenario.from_observation_map(obs["map"], obs["horizon"])
        geometry.tasks = [_task(j) for j in obs["pending"]]
        driver = PriorityDriver(OrderCosts(obs, geometry), [0, 1, 2])
        shadow = ShadowState.from_observation(obs, world_factory=Environment)
        slow = shadow.preview(driver(obs), rollout_policy=driver)
        fast = shadow.preview(driver(obs), rollout_policy=driver, pure_empty_skips=True)
        slow.pop("cpu_seconds")
        fast.pop("cpu_seconds")
        self.assertEqual(slow, fast)
        self.assertTrue(fast["completed"])

    def test_pure_skip_requires_explicit_policy_contract(self):
        s = generate_current(seed=60, task_count=1, vehicles=1, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        shadow = ShadowState.from_observation(obs, world_factory=Environment)
        with self.assertRaises(ValueError):
            shadow.preview([], rollout_policy=lambda obs: [], pure_empty_skips=True)

    def test_exact_matches_exhaustive_orders_and_real_execution(self):
        s = generate_current(seed=60, task_count=4, vehicles=1, mode="static", horizon=None)
        certificate = exact_single(s)
        router = Router(s)
        T0, R0, D0 = certificate["reference"]
        best = float("inf")
        for order in itertools.permutations(s.tasks):
            position, t, moves, completions, previous = s.homes[0], 0, 0, [], []
            for j in order:
                if any(
                    k.shelf == j.shelf
                    and (-k.shelf_level, k.id) < (-j.shelf_level, j.id)
                    and k not in previous
                    for k in s.tasks
                ):
                    break
                distance = min(
                    router.distance(position, p, 0) + router.distance(p, j.delivery, 0)
                    for p in s.pickup_candidates(j)
                )
                moves += distance
                t += distance + j.pickup_service + j.delivery_service
                completions.append(t)
                position = j.delivery
                previous.append(j)
            else:
                moves += router.distance(position, s.homes[0], 0)
                score = 0.5 * t / T0 + 0.3 * sum(completions) / len(order) / R0 + 0.2 * moves / D0
                best = min(best, score)
        self.assertAlmostEqual(best, certificate["optimal_score"])
        result = score_result(s, run(s, mode="exact"))
        self.assertTrue(validate(s, result))
        self.assertAlmostEqual(result["weighted_score"], best)

    def test_rejects_dynamic_or_multi_vehicle_exact_claims(self):
        for options in (dict(vehicles=2, mode="static"), dict(vehicles=1, mode="dynamic")):
            with self.assertRaises(ValueError):
                exact_single(generate_current(seed=60, task_count=4, horizon=None, **options))

    def test_layer_precedence_is_preserved(self):
        s = generate_current(
            seed=61, task_count=3, vehicles=1, mode="static", shelf_layers=8, horizon=None
        )
        base = next(j for j in s.tasks if j.shelf_level > 1)
        s.tasks = [
            replace(base, id=i, shelf_level=l, pickup_service=2 * l)
            for i, l in enumerate((2, 8, 5))
        ]
        s.check()
        c = exact_single(s)
        self.assertEqual(c["order"], [1, 2, 0])
        self.assertTrue(validate(s, score_result(s, run(s, mode="exact"))))

    def test_exact_rejects_finite_horizon_and_future_close(self):
        for options in (dict(horizon=1000), dict(horizon=None, order_stream_end=10)):
            s = generate_current(seed=60, task_count=2, vehicles=1, mode="static", **options)
            with self.assertRaises(ValueError):
                exact_single(s)

    def test_search_action_cannot_depend_on_hidden_orders_or_stream_end(self):
        a = generate_current(seed=60, task_count=2, vehicles=2, mode="static", horizon=None)
        a.tasks = [replace(a.tasks[0], release=0), replace(a.tasks[1], release=50)]
        a.order_stream_end = 60
        a.check()
        b = type(a).from_dict(a.to_dict())
        b.tasks = [b.tasks[0], replace(b.tasks[1], release=500, id=700)]
        b.order_stream_end = 900
        b.check()
        oa, ob = (
            Environment(a, router_kind="sipp").observe(),
            Environment(b, router_kind="sipp").observe(),
        )
        self.assertEqual(oa, ob)
        pa, pb = SearchPolicy(world_factory=Environment), SearchPolicy(world_factory=Environment)
        self.assertEqual(pa.action(oa), pb.action(ob))
        self.assertEqual(pa.decisions, pb.decisions)


if __name__ == "__main__":
    unittest.main()
