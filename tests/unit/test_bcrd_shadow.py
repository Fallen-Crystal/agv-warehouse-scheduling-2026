"""Observation-only previews are differential copies of real assign semantics."""

import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from agv.dispatch.shadow import ShadowState, _safe_greedy
from agv.domain import Task
from agv.evaluation.validation import validate
from agv.simulation import Environment
from agv.warehouse.layout import generate


def deterministic(result):
    return {key: value for key, value in result.items() if key != "cpu_seconds"}


def suffixes(env, start):
    return [past[start:] + plan[1:] for past, plan in zip(env._paths, env._plans)]


class ShadowTests(unittest.TestCase):
    def layers(self):
        scene = generate(task_count=0, vehicles=3)
        face = min(scene.shelves)
        opposite = (face[0], face[1] + 1)
        scene.tasks = [
            Task(0, None, scene.stations[0], shelf=face, pickup_service=6, shelf_level=3),
            Task(1, None, scene.stations[0], shelf=face, pickup_service=2),
            Task(2, None, scene.stations[0], shelf=opposite, pickup_service=4, shelf_level=2),
        ]
        return scene.check()

    def test_initial_batch_feedback_paths_and_order_match_real_executor(self):
        for backend in ("astar", "sipp"):
            for order in ([(0, 0), (1, 2)], [(1, 2), (0, 0)]):
                with self.subTest(backend=backend, order=order):
                    env = Environment(self.layers(), router_kind=backend)
                    observed = env.observe()
                    prediction = ShadowState.from_observation(observed, backend).preview(
                        order, depth=0
                    )
                    self.assertTrue(prediction["valid"], prediction["reason"])
                    feedback = env.assign(order)
                    self.assertEqual(prediction["feedback"], feedback)
                    self.assertEqual(prediction["paths"], env._plans)
                    self.assertEqual(prediction["assignments"], env._records)
                    self.assertEqual(prediction["residual_count"], 1)
                    self.assertEqual(prediction["routing_stats"], env._router.stats)

    def test_nonzero_time_active_loading_and_returning_suffix_are_preserved(self):
        scene = self.layers()
        for backend in ("astar", "sipp"):
            env = Environment(scene, router_kind=backend)
            env.assign([(0, 0), (1, 2)])
            loading = env._records[0]["pickup_arrival"] + 1
            env.advance(loading, observe=False)
            self.assertEqual(env.observe()["vehicles"][0]["state"], "loading")
            before, records = env.observe(), copy.deepcopy(env._records)
            prediction = ShadowState.from_observation(before, backend).preview([], depth=0)
            self.assertEqual(prediction["paths"], env._plans)
            self.assertEqual(prediction["assignments"], records)
            self.assertEqual(env.observe(), before)
            self.assertEqual(env._records, records)
            # Once the first delivery finishes, that vehicle is available while
            # its old return remains a real reservation for new candidates.
            end = max(record["delivery_end"] for record in env._records)
            env.advance(end - env.time, observe=False)
            before = env.observe()
            self.assertTrue(
                any(v["return_path"] and len(v["return_path"]) > 1 for v in before["vehicles"])
            )
            action = _safe_greedy(before)
            prediction = ShadowState.from_observation(before, backend).preview(action, depth=0)
            self.assertEqual(prediction["feedback"], env.assign(action))
            self.assertEqual(prediction["paths"], env._plans)
            self.assertEqual(
                prediction["assignments"], [r for r in env._records if r["assigned_at"] == end]
            )

    def test_full_visible_rollout_matches_actual_driver_and_independent_validation(self):
        for backend in ("astar", "sipp"):
            scene = generate(seed=12, task_count=8, vehicles=3, delivery_pattern="shared")
            env = Environment(scene, router_kind=backend)
            action = _safe_greedy(env.observe())
            prediction = ShadowState.from_observation(env.observe(), backend).preview(action)
            self.assertTrue(prediction["valid"], prediction["reason"])
            env.assign(action)
            while not env.done:
                env.advance(observe=False)
                if not env.done:
                    env.assign(_safe_greedy(env.observe()))
            result = env.result()
            self.assertTrue(validate(scene, result))
            self.assertEqual(prediction["paths"], result["paths"])
            self.assertEqual(prediction["assignments"], result["assignments"])
            self.assertEqual(prediction["predicted_T"], result["makespan"])
            self.assertEqual(prediction["additional_moves"], result["moves"])
            self.assertAlmostEqual(prediction["mean_flow_time"], result["mean_flow_time"])
            self.assertEqual(prediction["residual_count"], 0)

    def test_same_face_gate_and_invalid_batch_match_real_atomic_rejection(self):
        env = Environment(self.layers(), router_kind="sipp")
        for action in ([(0, 1)], [(0, 0), (1, 1)], [(0, 0), (0, 2)], [(8, 0)], "bad"):
            with self.subTest(action=action):
                before = env.observe()
                prediction = ShadowState.from_observation(before).preview(action, depth=0)
                self.assertFalse(prediction["valid"])
                self.assertEqual(prediction["assignments"], [])
                with self.assertRaises(ValueError):
                    env.assign(action)
                self.assertEqual(env.observe(), before)
        env.assign([(0, 0)])
        before = env.observe()
        prediction = ShadowState.from_observation(before).preview([(1, 1)], depth=0)
        self.assertFalse(prediction["valid"])
        self.assertEqual(env.observe(), before)

    def test_late_higher_layer_and_different_future_are_byte_identical(self):
        scene = self.layers()
        scene.tasks = [scene.tasks[1], replace(scene.tasks[0], release=999)]
        alternate = copy.deepcopy(scene)
        alternate.tasks = [scene.tasks[0], replace(self.layers().tasks[2], id=42, release=1001)]
        envs = [Environment(s, router_kind="sipp") for s in (scene, alternate)]
        self.assertEqual(envs[0].observe(), envs[1].observe())
        predictions = []
        for env in envs:
            before = env.observe()
            prediction = ShadowState.from_observation(before).preview([(0, 1)])
            predictions.append(json.dumps(deterministic(prediction), sort_keys=True))
            self.assertEqual(env.observe(), before)
            self.assertEqual(env._records, [])
            self.assertEqual(prediction["visible_task_count"], 1)
        self.assertEqual(*predictions)

    def test_prediction_is_repeatable_snapshot_isolation_and_no_normalization(self):
        env = Environment(generate(task_count=3, vehicles=2), router_kind="sipp")
        observed = env.observe()
        shadow = ShadowState.from_observation(observed)
        action = _safe_greedy(observed)
        first = deterministic(shadow.preview(action))
        observed["pending"].clear()
        env.assign(action)
        second = deterministic(shadow.preview(action))
        self.assertEqual(first, second)
        self.assertNotIn("weighted_score", first)
        self.assertNotIn("normalization_reference", first)

    def test_route_call_steps_and_soft_search_budgets_reject_safely(self):
        env = Environment(self.layers(), router_kind="sipp")
        before = env.observe()
        for budget, reason in (
            ({"max_route_calls": 0}, "budget_route_calls"),
            ({"max_route_calls": 1}, "budget_route_calls"),
            ({"max_expanded": 0}, "budget_expanded"),
            ({"max_cpu_seconds": 0}, "budget_cpu"),
            ({"max_steps": 0}, "budget_steps"),
        ):
            with self.subTest(budget=budget):
                prediction = ShadowState.from_observation(before).preview([(0, 0)], budget=budget)
                self.assertFalse(prediction["valid"])
                self.assertTrue(prediction["exhausted"])
                self.assertEqual(prediction["reason"], reason)
                if "max_route_calls" in budget:
                    self.assertLessEqual(
                        prediction["routing_stats"]["calls"], budget["max_route_calls"]
                    )
                self.assertEqual(env.observe(), before)
                self.assertEqual(env._records, [])

    def test_depth_truncation_reports_unassigned_residual_instead_of_fake_completion(self):
        env = Environment(self.layers(), router_kind="sipp")
        prediction = ShadowState.from_observation(env.observe()).preview([(0, 0)], depth=0)
        self.assertTrue(prediction["valid"])
        self.assertFalse(prediction["completed"])
        self.assertEqual(prediction["residual_count"], 2)
        self.assertEqual(prediction["reason"], "depth_limited")
        full = ShadowState.from_observation(env.observe()).preview([(0, 0)], depth=1)
        self.assertEqual(full["decision_rounds"], 1)
        self.assertGreater(full["residual_count"], 0)

    def test_dynamic_snapshots_match_real_assign_at_multiple_nonzero_times(self):
        snapshots = {0, 1, 5, 10, 15, 20, 30, 45, 60}
        for backend in ("astar", "sipp"):
            for seed in (4, 11):
                scene = generate(mode="dynamic", task_count=9, vehicles=3, seed=seed)
                env = Environment(scene, router_kind=backend)
                while not env.done and env.time <= 60:
                    observation = env.observe()
                    action = _safe_greedy(observation)
                    prediction = None
                    if env.time in snapshots:
                        prediction = ShadowState.from_observation(observation, backend).preview(
                            action, depth=0
                        )
                    feedback = env.assign(action)
                    if prediction is not None:
                        self.assertEqual(prediction["feedback"], feedback)
                        self.assertEqual(prediction["paths"], env._plans)
                        actual = {record["task_id"]: record for record in env._records}
                        for record in prediction["assignments"]:
                            self.assertEqual(record, actual[record["task_id"]])
                    env.advance(observe=False)

    def test_sole_exit_station_shared_reservations_and_started_unload(self):
        scene = generate(seed=5, task_count=5, vehicles=3)
        station = (0, 0)
        scene.blocked.remove(station)
        scene.stations = [station]
        free = {(x, y) for x in range(scene.width) for y in range(scene.height)} - scene.blocked
        scene.transit_only = free - scene.pickup_zones - set(scene.homes) - {station}
        scene.tasks = [replace(job, delivery=station) for job in scene.tasks]
        scene.check()
        self.assertEqual(list(scene.neighbors(station)), [(0, 1)])
        env = Environment(scene, router_kind="sipp")
        action = _safe_greedy(env.observe())
        prediction = ShadowState.from_observation(env.observe()).preview(action, depth=0)
        self.assertEqual(prediction["feedback"], env.assign(action))
        self.assertEqual(prediction["paths"], env._plans)
        end = min(record["delivery_arrival"] for record in env._records)
        env.advance(end, observe=False)
        self.assertTrue(any(v["state"] == "unloading" for v in env.observe()["vehicles"]))
        observed = env.observe()
        paths = copy.deepcopy(env._plans)
        prediction = ShadowState.from_observation(observed).preview([], depth=0)
        self.assertEqual(prediction["paths"], paths)
        self.assertEqual(env.observe(), observed)
        self.assertEqual(env._plans, paths)

    def test_unreleased_or_inconsistent_active_data_is_rejected(self):
        observed = Environment(self.layers()).observe()
        observed["pending"][0]["release"] = 99
        with self.assertRaisesRegex(ValueError, "unreleased"):
            ShadowState.from_observation(observed)
        observed = Environment(self.layers()).observe()
        observed["vehicles"][0]["available"] = False
        with self.assertRaisesRegex(ValueError, "requires"):
            ShadowState.from_observation(observed)

    def assert_event_equivalent(self, observation, action, backend="sipp", **kwargs):
        answers = [
            deterministic(
                ShadowState.from_observation(
                    observation, router_kind=backend, event_driven=enabled
                ).preview(action, **kwargs)
            )
            for enabled in (False, True)
        ]
        self.assertEqual(answers[0], answers[1])
        return answers[1]

    def test_event_replay_matches_stepwise_at_dynamic_and_service_snapshots(self):
        for backend in ("astar", "sipp"):
            for seed in (10, 11):
                scene = generate(
                    mode="dynamic",
                    seed=seed,
                    task_count=7,
                    vehicles=2,
                    delivery_pattern="shared",
                )
                env = Environment(scene, router_kind=backend)
                snapshots = {0, 1, 5, 15, 30, 45}
                while not env.done and env.time <= 45:
                    observation = env.observe()
                    action = _safe_greedy(observation)
                    if env.time in snapshots:
                        with self.subTest(backend=backend, seed=seed, time=env.time):
                            self.assert_event_equivalent(observation, action, backend)
                    env.assign(action)
                    env.advance(observe=False)

    def test_event_replay_keeps_depth_and_count_budget_boundaries_exact(self):
        scene = generate(seed=10, task_count=6, vehicles=2, delivery_pattern="shared")
        env = Environment(scene, router_kind="sipp")
        observation = env.observe()
        action = _safe_greedy(observation)
        for depth in (None, 0, 1, 2):
            for budget in (
                {},
                {"max_steps": 0},
                {"max_steps": 1},
                {"max_steps": 9},
                {"max_steps": 40},
                {"max_route_calls": 0},
                {"max_route_calls": 1},
                {"max_route_calls": 9},
                {"max_route_calls": 25},
                {"max_expanded": 0},
                {"max_expanded": 50},
                {"max_cpu_seconds": 0},
                {"max_cpu_seconds": 100},
            ):
                with self.subTest(depth=depth, budget=budget):
                    prediction = self.assert_event_equivalent(
                        observation, action, depth=depth, budget=budget
                    )
                    if prediction["reason"] == "budget_steps":
                        self.assertEqual(prediction["simulated_steps"], budget["max_steps"])
        # A finite horizon and existing commitments use the same clipped end.
        scene.horizon = 120
        env = Environment(scene, router_kind="sipp")
        action = _safe_greedy(env.observe())
        env.assign(action)
        env.advance(2, observe=False)
        for depth in (None, 0, 1):
            self.assert_event_equivalent(env.observe(), [], depth=depth)

    def test_event_replay_skips_empty_default_decisions_but_keeps_full_history(self):
        scene = generate(seed=10, task_count=4, vehicles=2)
        observation = Environment(scene, router_kind="sipp").observe()
        action = _safe_greedy(observation)
        real_advance = Environment.advance
        histories, calls = [], []
        for enabled in (False, True):
            advances, environments = [], []

            def recorded(env, steps=1, *, observe=True):
                advances.append((steps, len(env._assigned) == len(env._jobs), all(env._active)))
                environments.append(env)
                return real_advance(env, steps, observe=observe)

            with patch.object(Environment, "advance", recorded):
                prediction = ShadowState.from_observation(
                    observation, event_driven=enabled
                ).preview(action)
            last = environments[-1]
            histories.append((last._paths, last._interval_states, deterministic(prediction)))
            calls.append(advances)
        self.assertEqual(histories[0], histories[1])
        self.assertTrue(all(steps == 1 for steps, _, _ in calls[0]))
        self.assertTrue(any(steps > 1 for steps, _, _ in calls[1]))
        self.assertLess(len(calls[1]), len(calls[0]))
        self.assertTrue(all(steps == 1 or assigned or busy for steps, assigned, busy in calls[1]))

    def test_event_replay_custom_policy_is_called_at_every_step(self):
        scene = generate(seed=11, task_count=4, vehicles=2)
        observation = Environment(scene, router_kind="sipp").observe()
        action = _safe_greedy(observation)
        answers, times = [], []
        for enabled in (False, True):
            visited = []

            def policy(obs):
                visited.append(obs["time"])
                return _safe_greedy(obs)

            answers.append(
                deterministic(
                    ShadowState.from_observation(observation, event_driven=enabled).preview(
                        action, rollout_policy=policy
                    )
                )
            )
            times.append(visited)
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(times[0], times[1])
        self.assertGreater(len(times[0]), 10)
        self.assertTrue(all(b == a + 1 for a, b in zip(times[1], times[1][1:])))

    def test_event_replay_preserves_final_one_step_after_depth_limit(self):
        scene = generate(seed=10, task_count=6, vehicles=2)
        observation = Environment(scene, router_kind="sipp").observe()
        action = _safe_greedy(observation)
        real_advance = Environment.advance
        advances = []

        def recorded(env, steps=1, *, observe=True):
            advances.append(steps)
            return real_advance(env, steps, observe=observe)

        with patch.object(Environment, "advance", recorded):
            prediction = ShadowState.from_observation(observation).preview(action, depth=1)
        self.assertTrue(any(steps > 1 for steps in advances))
        self.assertEqual(advances[-1], 1)
        self.assertEqual(prediction["decision_rounds"], 1)
        self.assert_event_equivalent(observation, action, depth=1)

    def test_event_replay_requires_explicit_boolean_option(self):
        observation = Environment(self.layers()).observe()
        for invalid in (None, 0, 1, "yes"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "boolean"):
                    ShadowState.from_observation(observation, event_driven=invalid)

    def test_finite_horizon_failure_is_not_a_low_cost_success(self):
        scene = self.layers()
        scene.horizon = 1
        env = Environment(scene, router_kind="sipp")
        prediction = ShadowState.from_observation(env.observe()).preview([(0, 0)])
        self.assertFalse(prediction["valid"])
        self.assertFalse(prediction["completed"])
        self.assertEqual(prediction["reason"], "initial_route_failure")
        self.assertEqual(prediction["feedback"], env.assign([(0, 0)]))
        self.assertEqual(prediction["paths"], env._plans)


if __name__ == "__main__":
    unittest.main()
