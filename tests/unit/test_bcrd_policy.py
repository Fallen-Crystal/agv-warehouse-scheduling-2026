import unittest
from copy import deepcopy
from dataclasses import replace

from agv.dispatch.bcrd import bcrd_action, fallback, run
from agv.dispatch.candidates import legalize
from agv.evaluation.validation import validate
from agv.simulation import Environment
from agv.warehouse import generate


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in ("cpu_seconds", "wall_seconds")}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


class BCRDPolicyTests(unittest.TestCase):
    def test_visible_choice_is_deterministic_and_readonly(self):
        env = Environment(generate(task_count=5, vehicles=2, seed=10), router_kind="sipp")
        obs = env.observe()
        before = deepcopy(obs)
        first, second = [], []
        a = bcrd_action(obs, diagnostics=first, min_queue_ratio=0)
        b = bcrd_action(obs, diagnostics=second, min_queue_ratio=0)
        self.assertEqual(a, b)
        self.assertEqual(stable(first), stable(second))
        self.assertEqual(obs, before)
        self.assertEqual(env.observe(), before)
        self.assertEqual(legalize(a, obs), a)
        self.assertTrue(first[0]["candidates"])

    def test_future_replacement_invariance_while_searching(self):
        scene = generate(task_count=7, vehicles=2, seed=10)
        scene.tasks = scene.tasks[:5] + [replace(j, release=500 + j.id) for j in scene.tasks[5:]]
        altered = deepcopy(scene)
        altered.tasks = altered.tasks[:5] + [
            replace(j, id=j.id + 100, release=j.release + 99) for j in altered.tasks[5:][::-1]
        ]
        a = Environment(scene, router_kind="sipp").observe()
        b = Environment(altered, router_kind="sipp").observe()
        self.assertEqual(a, b)
        log_a, log_b = [], []
        self.assertEqual(
            bcrd_action(a, diagnostics=log_a, min_queue_ratio=0),
            bcrd_action(b, diagnostics=log_b, min_queue_ratio=0),
        )
        self.assertTrue(log_a[0]["candidates"])
        self.assertEqual(stable(log_a), stable(log_b))

    def test_event_execution_preserves_complete_dispatch_behavior(self):
        scene = generate(task_count=8, vehicles=2, seed=11)
        old = run(scene, min_queue_ratio=0, event_driven=False)
        fast = run(scene, min_queue_ratio=0, event_driven=True)
        validate(scene, old)
        validate(scene, fast)
        for field in (
            "paths",
            "assignments",
            "interval_states",
            "makespan",
            "mean_flow_time",
            "moves",
            "routing_stats",
        ):
            self.assertEqual(old[field], fast[field], field)
        self.assertEqual(stable(old["dispatch_decisions"]), stable(fast["dispatch_decisions"]))

    def test_zero_and_exhausted_budget_keep_greedy(self):
        obs = Environment(generate(task_count=5, vehicles=2, seed=10)).observe()
        self.assertEqual(bcrd_action(obs, max_batches=0), fallback(obs))
        for budget in ({"max_route_calls": 0}, {"max_route_calls": 1}, {"max_cpu_seconds": 0}):
            logs = []
            self.assertEqual(
                bcrd_action(obs, budget=budget, diagnostics=logs, min_queue_ratio=0), fallback(obs)
            )
            self.assertTrue(logs[0]["fallback"])
            self.assertLessEqual(logs[0]["shadow_route_calls"], budget.get("max_route_calls", 999))

    def test_partial_forecasts_cannot_win_by_omission(self):
        obs = Environment(generate(task_count=8, vehicles=2, seed=10)).observe()
        logs = []
        self.assertEqual(
            bcrd_action(obs, depth=0, diagnostics=logs, min_queue_ratio=0), fallback(obs)
        )
        self.assertFalse(logs[0]["candidates"][0]["valid"])
        self.assertGreater(logs[0]["candidates"][0]["residual_count"], 0)

    def test_complete_execution_and_no_future_peeking(self):
        scene = generate(task_count=5, vehicles=2, seed=10)
        r = run(scene, min_queue_ratio=0)
        validate(scene, r)
        self.assertTrue(r["feasible"])
        self.assertGreater(r["dispatch_stats"]["changed"], 0)
        future = deepcopy(scene)
        future.tasks = [future.tasks[0]] + [
            replace(j, release=500 + j.id) for j in future.tasks[1:]
        ]
        first = Environment(future).observe()
        changed = deepcopy(future)
        changed.tasks = [changed.tasks[0]] + [
            replace(j, release=j.release + 99) for j in changed.tasks[1:]
        ]
        second = Environment(changed).observe()
        self.assertEqual(first, second)
        self.assertEqual(bcrd_action(first), bcrd_action(second))


if __name__ == "__main__":
    unittest.main()
