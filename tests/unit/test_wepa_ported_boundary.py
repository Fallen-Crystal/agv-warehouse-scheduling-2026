"""Behavioral checks for public closure, physical waiting and admissible pruning."""

import unittest
from copy import deepcopy
from unittest.mock import patch

from agv.core.objectives import LinearObjective
from agv.evaluation.objectives.linear_f import checked_score
from agv.policy.wepa.common import values
from agv.policy.wepa.forecast import rollout, snapshot
from agv.policy.wepa.legacy.proxy import MixedCosts as OldCosts
from agv.policy.wepa.proxy import MixedCosts, standby_distance
from agv.runner.wepa import run
from agv.world.wepa_snapshot import ShadowWorld
from tests.exact.fixtures import new_world as World
from tests.unit.test_wepa_ported_variants import model


class BoundaryTests(unittest.TestCase):
    def view(self, closed=False):
        w = World(model(300))
        w.publish_and_complete()
        if closed:
            w.model["tasks"] = [j for j in w.tasks.values() if j["release"] == 0]
            w.tasks = {j["id"]: j for j in w.model["tasks"]}
            w.model["close_at"] = 0
            w.publish_and_complete()
        return snapshot(w, terminal="standby")

    def test_repeated_snapshots_preserve_public_open_flag(self):
        v = self.view()
        for _ in range(4):
            self.assertFalse(v.closed)
            self.assertFalse(v.observed_closed)
            self.assertEqual(set(v.tasks), {0, 1, 2, 3})
            self.assertEqual(v.model["close_at"], float("inf"))
            v = snapshot(v)

    def test_open_rollout_ends_in_executor_stable_safe_standby(self):
        v = self.view()
        before = deepcopy(v.plans)
        trial, usage = rollout(v)
        self.assertIsNotNone(trial)
        self.assertEqual(usage["reason"], "complete_standby")
        self.assertFalse(trial.closed)
        self.assertEqual(set(trial.completed), set(v.tasks))
        self.assertTrue(any(p[0] != trial.scene.homes[k] for k, p in enumerate(trial.plans)))
        for k, p in enumerate(trial.plans):
            self.assertTrue(trial.ordinary(p[0]) or p[0] == trial.scene.homes[k])
        stable = deepcopy(trial.plans)
        distance = trial.past_moves
        for _ in range(20):
            trial.publish_and_complete()
            trial.advance()
            self.assertEqual(trial.plans, stable)
            self.assertEqual(trial.past_moves, distance)
        self.assertEqual(v.plans, before)

    def test_closed_forecast_still_returns_home(self):
        v = self.view(closed=True)
        trial, usage = rollout(v)
        self.assertTrue(trial.done)
        self.assertEqual(usage["reason"], "complete")
        self.assertTrue(trial.closed)
        for k, p in enumerate(trial.plans):
            self.assertEqual(p, [trial.scene.homes[k]])

    def test_closed_static_problem_has_exact_same_execution(self):
        m = model(0)
        a, b = run(m, "gate", seed=2), run(m, "open_gate", seed=2)
        for key in ("paths", "labels", "records", "decisions", "T", "R", "D"):
            self.assertEqual(a[key], b[key])

    def test_empty_known_prefix_has_zero_cost_and_no_ghost_return(self):
        w = World(model(300))
        w.model["tasks"] = []
        w.tasks = {}
        w.publish_and_complete()
        trial, usage = rollout(snapshot(w, terminal="standby"))
        self.assertEqual(values(trial), (0, 0, 0))
        self.assertEqual(usage["reason"], "complete_standby")
        self.assertFalse(trial.closed)

    def test_open_fast_and_tick_rollouts_agree(self):
        v = self.view()
        fast, _ = rollout(v)
        with patch.object(ShadowWorld, "jump_quiet", return_value=False):
            slow, _ = rollout(v)
        self.assertEqual(values(fast), values(slow))
        self.assertEqual(fast.records, slow.records)
        self.assertEqual(fast.plans, slow.plans)

    def test_pruning_preserves_strictly_better_open_candidate(self):
        v = self.view()
        trial, _ = rollout(v)
        obj = LinearObjective(vehicles=2)
        incumbent = obj.score(values(trial)) + 1e-9
        again, usage = rollout(v, objective=obj, incumbent=incumbent)
        self.assertIsNotNone(again, usage)
        self.assertEqual(values(trial), values(again))
        _, usage = rollout(v, objective=obj, incumbent=0)
        self.assertEqual(usage["reason"], "bound_pruned")

    def test_proxy_preserves_closed_and_reduces_open_terminal_distance_only(self):
        v = self.view()
        trial, _ = rollout(v)
        order = [
            r["task"]
            for r in sorted(
                trial.records, key=lambda r: (r["assigned_at"], r["vehicle"], r["task"])
            )
        ]
        owners = {r["task"]: r["vehicle"] for r in trial.records}
        old = OldCosts(v, trial).estimate_joint(order, owners)
        new = MixedCosts(v, trial).estimate_joint(order, owners)
        self.assertEqual(old[:2], new[:2])
        self.assertLess(new[2], old[2])
        v.observed_closed = True
        self.assertEqual(old, MixedCosts(v, trial).estimate_joint(order, owners))
        for k, p in enumerate(trial.plans):
            self.assertEqual(standby_distance(v, p[0], k), 0)

    def test_actual_final_return_and_full_scoring_are_unchanged(self):
        m = model(300)
        r = run(m, "open_gate", seed=1, objective=LinearObjective(vehicles=2))
        self.assertTrue(checked_score(m, r, LinearObjective(vehicles=2))["audit"]["valid"])
        self.assertGreaterEqual(r["time"], m["close_at"])
        for k, path in enumerate(r["paths"]):
            self.assertEqual(tuple(path[-1]), m["scene"].homes[k])
        self.assertGreater(r["D"], 0)
        self.assertEqual(r["D"], sum(a != b for p in r["paths"] for a, b in zip(p, p[1:])))

    def test_open_policy_does_not_read_unpublished_jobs_or_close_time(self):
        a, b = model(300), model(400)
        x, y = run(a, "open_gate", seed=2), run(b, "open_gate", seed=2)
        self.assertEqual(
            [d for d in x["decisions"] if d["time"] < 300],
            [d for d in y["decisions"] if d["time"] < 300],
        )
        for p, q in zip(x["paths"], y["paths"]):
            self.assertEqual(p[:301], q[:301])


if __name__ == "__main__":
    unittest.main()
