"""Current-stream forecasts stop at known work, without inventing a close event."""

import unittest
from copy import deepcopy
from dataclasses import replace
from time import process_time

from agv.dispatch.bcrd import bcrd_action, fallback
from agv.dispatch.registry import run_named
from agv.dispatch.shadow import ShadowState, _safe_greedy
from agv.evaluation.validation import validate
from agv.simulation import Environment
from agv.warehouse.mixed import generate_current


def stable(value):
    if isinstance(value, dict):
        return {
            key: stable(item)
            for key, item in value.items()
            if key not in ("cpu_seconds", "wall_seconds")
        }
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def fixture(*, closed=False, count=6, seed=10):
    return generate_current(
        seed=seed,
        task_count=count,
        vehicles=2,
        order_stream_end=0 if closed else 1000,
        horizon=2000,
    )


def visible_ids(observation):
    return {job["id"] for job in observation["pending"]} | {
        vehicle["task_id"] for vehicle in observation["vehicles"] if vehicle["task_id"] is not None
    }


def advance_known(env):
    """Reference stepwise real execution: stop when its current jobs finish."""
    while len(env._assigned) < len(env._released_jobs) or any(env._active):
        env.advance(observe=False)
        env.assign(_safe_greedy(env.observe()))
        if env.time > 900:
            raise AssertionError("Known-work test unexpectedly reached the publisher close")


class CurrentStreamShadowTests(unittest.TestCase):
    def test_hidden_future_replacement_keeps_preview_and_action_identical(self):
        left = fixture()
        left.tasks.append(replace(left.tasks[0], id=99, release=900))
        right = deepcopy(left)
        right.tasks[-1] = replace(right.tasks[-1], id=101, release=950, delivery=right.stations[0])
        a, b = (Environment(s.check(), router_kind="sipp") for s in (left, right))
        before = deepcopy(a.observe())
        self.assertEqual(before, b.observe())
        batch = fallback(before)
        estimates = [ShadowState.from_observation(env.observe()).preview(batch) for env in (a, b)]
        self.assertEqual(stable(estimates[0]), stable(estimates[1]))
        logs = [[], []]
        actions = [
            bcrd_action(env.observe(), min_queue_ratio=0, diagnostics=log, tail_guard=True)
            for env, log in zip((a, b), logs)
        ]
        self.assertEqual(actions[0], actions[1])
        self.assertEqual(stable(logs[0]), stable(logs[1]))
        self.assertTrue(logs[0][0]["candidates"])
        self.assertEqual(a.observe(), before)
        self.assertEqual(a.observe(), b.observe())

    def test_open_empty_preview_does_not_close_or_predict_fallback_return(self):
        env = Environment(fixture(count=1), router_kind="sipp")
        env.assign(fallback(env.observe()))
        env.advance(env._records[0]["delivery_end"] + 1, observe=False)
        before = deepcopy(env.observe())
        self.assertFalse(before["order_stream_closed"])
        self.assertTrue(any(len(v["return_path"]) > 1 for v in before["vehicles"]))
        prediction = ShadowState.from_observation(before).preview([])
        self.assertTrue(prediction["valid"])
        self.assertTrue(prediction["completed"])
        self.assertEqual(prediction["visible_task_count"], 0)
        self.assertEqual(prediction["simulated_steps"], 0)
        self.assertEqual(prediction["additional_moves"], 0)
        self.assertEqual(prediction["predicted_T"], env.time)
        self.assertEqual(prediction["paths"], [[tuple(v["position"])] for v in before["vehicles"]])
        self.assertNotEqual(prediction["paths"][0][-1], env._scenario.homes[0])
        self.assertEqual(env.observe(), before)

    def test_open_forecast_matches_real_stepwise_known_work_without_final_return(self):
        env = Environment(fixture(), router_kind="sipp")
        original = deepcopy(env.observe())
        batch = fallback(original)
        prediction = ShadowState.from_observation(original).preview(batch)
        self.assertTrue(prediction["valid"], prediction["reason"])
        self.assertFalse(original["order_stream_closed"])
        env.assign(batch)
        advance_known(env)
        self.assertFalse(env.observe()["order_stream_closed"])
        self.assertEqual(prediction["paths"], env._paths)
        self.assertEqual(prediction["assignments"], env._records)
        self.assertEqual(prediction["predicted_T"], env.time)
        self.assertEqual(
            prediction["additional_moves"],
            sum(a != b for p in env._paths for a, b in zip(p, p[1:])),
        )
        self.assertTrue(
            any(path[-1] != home for path, home in zip(prediction["paths"], env._scenario.homes))
        )
        self.assertNotIn("order_stream_end", original)

    def test_closed_forecast_includes_real_final_home_returns(self):
        s = fixture(closed=True, count=4)
        env = Environment(s, router_kind="sipp")
        batch = fallback(env.observe())
        prediction = ShadowState.from_observation(env.observe()).preview(batch)
        env.assign(batch)
        while not env.done:
            env.advance(observe=False)
            env.assign(_safe_greedy(env.observe()))
        result = env.result()
        self.assertTrue(validate(s, result))
        self.assertTrue(prediction["valid"])
        self.assertEqual(prediction["paths"], result["paths"])
        self.assertEqual(prediction["additional_moves"], result["moves"])
        self.assertEqual([path[-1] for path in prediction["paths"]], s.homes)

    def test_nonzero_old_return_and_visible_active_commitments_match_stepwise(self):
        env = Environment(fixture(count=6, seed=11), router_kind="sipp")
        env.assign(fallback(env.observe()))
        end = min(record["delivery_end"] for record in env._records)
        env.advance(end + 1, observe=False)
        original, origin = deepcopy(env.observe()), env.time
        self.assertTrue(original["completed"])
        self.assertTrue(any(v["route_record"] and v["available"] for v in original["vehicles"]))
        self.assertTrue(any(not v["available"] for v in original["vehicles"]))
        shadow = ShadowState.from_observation(original, event_driven=False)
        recreated = shadow._environment({}, process_time())
        for _ in range(5):
            self.assertEqual(recreated.observe(), env.observe())
            # Also compare exact reservation suffixes independently from the
            # serialized observation contract.
            self.assertEqual(recreated._plans, env._plans)
            for a, b in zip(recreated.observe()["vehicles"], env.observe()["vehicles"]):
                for field in ("position", "available", "task_id", "return_path", "committed_path"):
                    self.assertEqual(a[field], b[field])
            self.assertEqual(recreated.observe()["pending"], env.observe()["pending"])
            actions = [_safe_greedy(item.observe()) for item in (recreated, env)]
            self.assertEqual(actions[0], actions[1])
            recreated.assign(actions[0])
            env.assign(actions[1])
            recreated.advance(observe=False)
            env.advance(observe=False)
        # Also compare a fresh whole preview at the original nonzero snapshot.
        real = Environment(fixture(count=6, seed=11), router_kind="sipp")
        real.assign(fallback(real.observe()))
        real.advance(origin, observe=False)
        batch = fallback(original)
        prediction = shadow.preview(batch)
        real.assign(batch)
        advance_known(real)
        known = visible_ids(original)
        records = [r for r in real._records if r["task_id"] in known]
        self.assertTrue(prediction["valid"], prediction["reason"])
        self.assertEqual(prediction["assignments"], records)
        self.assertEqual(prediction["paths"], [path[origin:] for path in real._paths])

    def test_open_event_skip_matches_one_step_replay_and_safety_budgets(self):
        observation = Environment(fixture(count=4), router_kind="sipp").observe()
        batch = fallback(observation)
        for budget in ({}, {"max_steps": 1}, {"max_route_calls": 1}, {"max_cpu_seconds": 0}):
            answers = [
                ShadowState.from_observation(observation, event_driven=enabled).preview(
                    batch, budget=budget
                )
                for enabled in (False, True)
            ]
            self.assertEqual(stable(answers[0]), stable(answers[1]))
            if budget:
                self.assertFalse(answers[0]["valid"])
                self.assertTrue(answers[0]["exhausted"])
        for budget in ({"max_route_calls": 0}, {"max_route_calls": 1}, {"max_cpu_seconds": 0}):
            logs = []
            self.assertEqual(
                bcrd_action(observation, min_queue_ratio=0, budget=budget, diagnostics=logs), batch
            )
            self.assertTrue(logs[0]["fallback"])
            self.assertLessEqual(logs[0]["shadow_route_calls"], budget.get("max_route_calls", 1000))

    def test_tail_guard_candidates_cannot_accept_worse_visible_p90(self):
        observation = Environment(fixture(), router_kind="sipp").observe()
        # Previously completed flow times belong to the visible observation,
        # not an offline reference. Include them in every compared candidate.
        observation["completed_flow_times"] = [500, 1, 2]
        before, logs = deepcopy(observation), []
        bcrd_action(observation, min_queue_ratio=0, tail_guard=True, diagnostics=logs)
        candidates = logs[0]["candidates"]
        self.assertTrue(candidates)
        incumbent = next(row["predicted_p90"] for row in candidates if row["id"] == "greedy")
        self.assertEqual(incumbent, 500)
        chosen = logs[0]["chosen"]
        selected = next(row for row in candidates if row["id"] == chosen)
        self.assertFalse(selected["tail_rejected"])
        self.assertLessEqual(selected["predicted_p90"], incumbent)
        for row in candidates:
            if row["valid"] and not row["tail_rejected"]:
                self.assertLessEqual(row["predicted_p90"], incumbent)
        self.assertEqual(observation, before)

    def test_tail_guard_actually_rejects_a_worse_p90_forecast(self):
        observation = Environment(fixture(), router_kind="sipp").observe()
        logs = []
        bcrd_action(observation, min_queue_ratio=0, tail_guard=True, diagnostics=logs)
        candidates = logs[0]["candidates"]
        incumbent = next(row["predicted_p90"] for row in candidates if row["id"] == "greedy")
        rejected = [row for row in candidates if row["tail_rejected"]]
        self.assertTrue(rejected)
        self.assertTrue(all(row["predicted_p90"] > incumbent for row in rejected))
        chosen = next(row for row in candidates if row["id"] == logs[0]["chosen"])
        self.assertLessEqual(chosen["predicted_p90"], incumbent)

    def test_positioning_combination_and_old_registry_name_remain_explicitly_rejected(self):
        s = fixture(count=2)
        observation = Environment(s, positioning=True).observe()
        with self.assertRaisesRegex(ValueError, "separately validated"):
            bcrd_action(observation)
        with self.assertRaises(ValueError):
            run_named("bcrd_budget", s)
        for name in ("sipp_stream_bcrd", "sipp_stream_bcrd_tail"):
            result = run_named(name, fixture(closed=True, count=2))
            self.assertTrue(result["feasible"])
            self.assertTrue(validate(fixture(closed=True, count=2), result))


if __name__ == "__main__":
    unittest.main()
