"""Mechanism checks for independent, opt-in WEPA search interventions."""

import itertools
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agv.core.objectives import LinearObjective
from agv.policy.wepa.genetic import move_tail
from agv.policy.wepa.policy import ResearchPolicy
from agv.policy.wepa.profiles import PROFILES


class SearchInterventionTests(unittest.TestCase):
    def test_base_gate_configuration_stays_unchanged(self):
        self.assertEqual(
            PROFILES["gate"],
            dict(proxy=192, previews=6, generations=16, gate=True, anchor=False, repair=0),
        )
        self.assertFalse(PROFILES["gate_anchor"].get("hungarian_seeds", False))
        self.assertEqual(PROFILES["gate_anchor"]["base_previews"], 6)
        self.assertEqual(PROFILES["gate_anchor"]["previews"], 7)

    def search(self, profile, *, closed=True, anchor_values=(90, 50, 100)):
        objective = LinearObjective(vehicles=2)
        policy = ResearchPolicy(profile, 0, objective=objective)
        view = SimpleNamespace(
            tasks={j: dict(id=j, release=0) for j in range(3)},
            assigned=set(),
            visible={j: {} for j in range(3)},
            plans=[[], []],
            time=0,
            closed=True,
            observed_closed=closed,
        )
        owners = {j: j % 2 for j in range(3)}
        base = SimpleNamespace(value=(100, 50, 100), plan=([0, 1, 2], owners))
        worse = SimpleNamespace(value=(101, 50, 100), plan=base.plan)
        better = SimpleNamespace(value=anchor_values, plan=([2, 1, 0], owners))
        calls = []

        def rollout(_view, plan=None, *args, rule="eta", **kwargs):
            calls.append((plan, rule))
            return (better if rule == "hungarian" else base if plan is None else worse), {}

        plans = [(list(o), owners, "ga") for o in itertools.permutations(range(3))]
        with (
            patch("agv.policy.wepa.policy.rollout", side_effect=rollout),
            patch("agv.policy.wepa.policy.values", side_effect=lambda value: value.value),
            patch("agv.policy.wepa.policy.plan_from_prediction", side_effect=lambda p, _: p.plan),
            patch("agv.policy.wepa.policy.MixedCosts", return_value=SimpleNamespace(evaluations=0)),
            patch("agv.policy.wepa.policy.candidates", return_value=(plans, {})) as generate,
        ):
            policy.search(view)
        return policy, calls, generate.call_args.kwargs

    def test_second_anchor_preserves_six_original_previews_then_adds_one(self):
        base, original_calls, _ = self.search("gate")
        alternate, calls, _ = self.search("gate_anchor")
        self.assertEqual(len(original_calls), 6)
        self.assertEqual(calls[:-1], original_calls)
        self.assertEqual(calls[-1][1], "hungarian")
        self.assertEqual(alternate.logs[-1]["previews"], 7)
        self.assertLess(alternate.logs[-1]["score"], base.logs[-1]["score"])
        self.assertEqual(alternate.logs[-1]["candidates"][-1]["kind"], "hungarian_anchor")

    def test_tail_ranking_requires_observed_closure(self):
        _, _, open_kwargs = self.search("gate_tail", closed=False)
        _, _, closed_kwargs = self.search("gate_tail", closed=True)
        self.assertFalse(open_kwargs["tail"])
        self.assertTrue(closed_kwargs["tail"])

    def test_better_tail_time_cannot_bypass_the_real_F_acceptance(self):
        original, _, _ = self.search("gate")
        alternate, _, _ = self.search("gate_anchor", anchor_values=(90, 500, 100))
        self.assertEqual(alternate.plan, original.plan)
        self.assertEqual(alternate.logs[-1]["score"], original.logs[-1]["score"])

    def test_move_tail_preserves_task_membership_and_changes_only_pending_owner(self):
        costs = SimpleNamespace(
            obs={"vehicles": [{}, {}]},
            world=SimpleNamespace(time=10),
            projected={0: {"end": 30}, 1: {"end": 90}, 2: {"end": 120}},
        )
        order, owners = [0, 1, 2], {0: 0, 1: 1, 2: 1}
        sequence, assignment = move_tail(costs, order, owners)
        self.assertEqual(set(sequence), set(order))
        self.assertEqual(assignment, {0: 0, 1: 1, 2: 0})
        self.assertEqual(owners, {0: 0, 1: 1, 2: 1})
        self.assertEqual(sequence[-1], 2)

    def test_small_backlog_uses_cheap_matching_without_search(self):
        policy = ResearchPolicy("gate_trigger", 0, objective=LinearObjective(vehicles=2))
        world = SimpleNamespace(
            visible={j: {} for j in range(4)},
            assigned=set(),
            active=[None, None],
            completed=set(),
            time=0,
            closed=False,
        )
        with (
            patch.object(policy, "search") as search,
            patch("agv.policy.wepa.policy.matching_hungarian", return_value=([], {})) as matching,
        ):
            self.assertEqual(policy.action(world), [])
        search.assert_not_called()
        matching.assert_called_once()
        self.assertEqual(policy.logs[-1]["mode"], "backlog_trigger_skip")

    def test_closed_small_backlog_still_runs_the_original_search(self):
        policy = ResearchPolicy("gate_trigger", 0, objective=LinearObjective(vehicles=2))
        world = SimpleNamespace(
            visible={j: {} for j in range(3)},
            assigned=set(),
            active=[None, None],
            completed=set(),
            time=0,
            closed=True,
        )
        with (
            patch.object(policy, "search") as search,
            patch("agv.policy.wepa.policy.snapshot", return_value=world),
            patch("agv.policy.wepa.common.batch", return_value=[]),
            patch("agv.policy.wepa.policy.matching_hungarian") as matching,
        ):
            policy.action(world)
        search.assert_called_once_with(world)
        matching.assert_not_called()

    def test_tail_policy_does_not_read_hidden_release_or_close_time(self):
        from agv.data.wepa import build
        from agv.runner.wepa import run

        def model(future):
            jobs = [
                dict(
                    id=i,
                    source_row=i,
                    kind="retrieval" if i < 3 else "delivery",
                    sku=10,
                    release=0 if i < 3 else future,
                    source_time=0,
                    source_dock=1,
                    batch=i,
                    week=1,
                )
                for i in range(4)
            ]
            return build(
                dict(case="tail-privacy", initial={"10": 5}, close_at=future, tasks=jobs),
                size="medium",
                vehicles=2,
            )

        first, second = run(model(200), "gate_tail", seed=4), run(model(300), "gate_tail", seed=4)
        self.assertTrue(first["valid"] and second["valid"])
        self.assertEqual(
            [d for d in first["decisions"] if d["time"] < 200],
            [d for d in second["decisions"] if d["time"] < 200],
        )
        self.assertEqual([p[:200] for p in first["paths"]], [p[:200] for p in second["paths"]])


if __name__ == "__main__":
    unittest.main()
