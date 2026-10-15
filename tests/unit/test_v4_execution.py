"""Execution regressions for the V4 warehouse profile and its online boundary."""

import copy
import random
import unittest
from dataclasses import replace
from unittest.mock import patch

from agv.dispatch.greedy import run as run_baseline
from agv.dispatch.registry import run_named
from agv.domain import Scenario, Task
from agv.evaluation.metrics import summarize
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.planning.joint import repair_vehicle
from agv.planning.pickup import plan_task
from agv.planning.sipp import SafeIntervalRouter
from agv.simulation import Environment
from agv.warehouse.layout import generate


class V4ExecutionTests(unittest.TestCase):
    def fixture(self, vehicles=3):
        scene = generate(task_count=0, vehicles=vehicles)
        upper = min(scene.shelves)
        lower = (upper[0], upper[1] + 1)
        self.assertIn(lower, scene.shelves)
        scene.tasks = [
            Task(0, None, scene.stations[0], pickup_service=2, shelf=upper, shelf_level=1),
            Task(1, None, scene.stations[0], pickup_service=6, shelf=upper, shelf_level=3),
            Task(2, None, scene.stations[0], pickup_service=4, shelf=upper, shelf_level=2),
            Task(3, None, scene.stations[1], pickup_service=2, shelf=lower, shelf_level=1),
        ]
        return scene.check(), upper, lower

    def finish(self, env, limit=3000):
        while not env.done and env.time < limit:
            env.advance(observe=False)
        self.assertTrue(env.done)
        return env.result()

    def test_generated_profile_runs_with_legacy_and_sipp_joint_solvers(self):
        for mode in ("static", "dynamic"):
            scene = generate(mode=mode, seed=3, task_count=10)
            for solver in ("baseline", "matching_only", "sipp_budget"):
                with self.subTest(mode=mode, solver=solver):
                    result = run_named(solver, scene)
                    self.assertTrue(result["feasible"], result.get("reason"))
                    self.assertTrue(validate(scene, result))
                    self.assertTrue(result["score_valid"])
                    self.assertAlmostEqual(
                        result["weighted_score"],
                        0.5 * result["normalized_time"]
                        + 0.3 * result["normalized_response"]
                        + 0.2 * result["normalized_distance"],
                    )

    def test_layer_gate_allows_opposite_face_and_releases_at_pickup_end(self):
        scene, upper, lower = self.fixture()
        env = Environment(scene, router_kind="sipp")
        with self.assertRaises(ValueError):
            env.assign([(0, 0)])
        feedback = env.assign([(0, 1), (1, 3)])
        self.assertTrue(all(item["accepted"] for item in feedback))
        self.assertNotEqual(upper, lower)
        with self.assertRaises(ValueError):
            env.assign([(2, 2)])
        end = env._records[0]["pickup_end"]
        env.advance(end)
        self.assertTrue(next(j for j in env.observe()["pending"] if j["id"] == 2)["dispatchable"])
        self.assertTrue(env.assign([(2, 2)])[0]["accepted"])
        self.assertTrue(validate(scene, env.result()))

    def test_same_face_batch_is_rejected_atomically(self):
        scene, _, _ = self.fixture()
        env = Environment(scene)
        before = env.observe()
        with self.assertRaises(ValueError):
            env.assign([(0, 1), (1, 2)])
        self.assertEqual(env.observe(), before)
        self.assertEqual(env._records, [])

    def test_future_high_layer_neither_blocks_nor_preempts_current_low_layer(self):
        scene, _, _ = self.fixture()
        scene.tasks = [scene.tasks[0], replace(scene.tasks[1], release=2)]
        visible_only = copy.deepcopy(scene)
        visible_only.tasks = visible_only.tasks[:1]
        env, alternate = Environment(scene), Environment(visible_only)
        self.assertEqual(env.observe(), alternate.observe())
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        self.assertTrue(alternate.assign([(0, 0)])[0]["accepted"])
        self.assertEqual(env.observe(), alternate.observe())
        original = copy.deepcopy(env._records[0])
        env.advance(2)
        self.assertEqual(env._records[0], original)
        self.assertEqual(env.observe()["vehicles"][0]["task_id"], 0)
        pending = next(j for j in env.observe()["pending"] if j["id"] == 1)
        self.assertFalse(pending["dispatchable"])

    def test_observation_keeps_future_reference_and_generation_seed_private(self):
        scene = generate(mode="dynamic", task_count=12, seed=7)
        env = Environment(scene)
        result = run_named("baseline", scene)
        self.assertIn("normalization_reference", result)
        observation = env.observe()
        forbidden = {"seed", "scenario_sha256", "normalization_reference", "weighted_score"}

        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & value.keys())
                for item in value.values():
                    inspect(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    inspect(item)

        inspect(observation)
        self.assertTrue(all(j["release"] <= observation["time"] for j in observation["pending"]))

    def test_started_multistep_loading_is_preserved_by_suffix_repair(self):
        scene, _, _ = self.fixture(vehicles=1)
        scene.tasks = [scene.tasks[1]]
        env = Environment(scene, router_kind="sipp")
        self.assertTrue(env.assign([(0, 1)])[0]["accepted"])
        record = copy.deepcopy(env._records[0])
        env.advance(record["pickup_arrival"] + 1)
        vehicle = env.observe()["vehicles"][0]
        self.assertEqual(vehicle["state"], "loading")
        path, repaired = repair_vehicle(
            scene, SafeIntervalRouter(scene), vehicle, env.time, set(), set()
        )
        self.assertEqual(repaired["pickup_arrival"], record["pickup_arrival"])
        self.assertEqual(repaired["pickup_end"], record["pickup_end"])
        remaining = record["pickup_end"] - env.time
        self.assertEqual(path[: remaining + 1], [vehicle["position"]] * (remaining + 1))

    def test_validator_uses_task_identity_when_optional_shelf_metadata_is_missing(self):
        # A valid route can still violate dispatch commitment capacity: this
        # counterfeit binds car 1 before car 0 has finished the same-face pickup.
        scene, _, _ = self.fixture(vehicles=2)
        scene.tasks = [scene.tasks[1], scene.tasks[0]]
        env = Environment(scene)
        self.assertTrue(env.assign([(0, 1)])[0]["accepted"])
        env.advance(env._records[0]["pickup_end"])
        self.assertTrue(env.assign([(1, 0)])[0]["accepted"])
        good = self.finish(env)
        self.assertTrue(validate(scene, good))
        bad = copy.deepcopy(good)
        old_start = bad["assignments"][1]["assigned_at"]
        bad["assignments"][0].pop("shelf")
        bad["assignments"][1]["assigned_at"] = 0
        bad["events"] = copy.deepcopy(bad["assignments"])
        for t in range(old_start):
            self.assertEqual(bad["interval_states"][1][t], "idle")
            bad["interval_states"][1][t] = "to_pickup"
        bad["idle_steps"] -= old_start
        bad["traffic_wait_steps"] += old_start
        bad.update(summarize(scene, bad))
        with self.assertRaisesRegex(ValueError, "face|layer|pickup"):
            validate(scene, bad)

    def test_station_only_authorizes_unloading_and_forbids_transit(self):
        scene = Scenario(
            3,
            1,
            set(),
            set(),
            [(0, 0)],
            [],
            horizon=None,
            stations=[(1, 0)],
            map_info={"station_access": "delivery_only", "model_version": "math-v4-integrated"},
        )
        for cls in (Router, SafeIntervalRouter):
            router = cls(scene)
            self.assertIsNone(router.leg((0, 0), (2, 0), 0, 0, set(), set()))
            self.assertIsNone(router.leg((0, 0), (1, 0), 0, 0, set(), set()))
            self.assertEqual(
                router.leg(
                    (0, 0),
                    (1, 0),
                    0,
                    0,
                    set(),
                    set(),
                    service=1,
                    delivery_station=(1, 0),
                ),
                [(0, 0), (1, 0), (1, 0)],
            )
            self.assertIsNone(router.leg((1, 0), (2, 0), 0, 0, {(1, (0, 0)), (1, (2, 0))}, set()))
        valid_scene = generate(task_count=0, vehicles=1)
        bad = Environment(valid_scene).result()
        # Insert a physically reachable visit to D in an empty-task execution.
        station = valid_scene.stations[0]
        path = Router(valid_scene).leg(
            valid_scene.homes[0],
            station,
            0,
            0,
            set(),
            set(),
            service=1,
            delivery_station=station,
        )
        back = Router(valid_scene).leg(
            station, valid_scene.homes[0], len(path) - 1, 0, set(), set()
        )
        path.extend(back[1:])
        bad.update(time=len(path) - 1, paths=[path])
        with self.assertRaisesRegex(ValueError, "station|Station"):
            validate(valid_scene, bad)

    def test_sipp_strict_station_matches_time_expanded_reference(self):
        scene = Scenario(
            4,
            3,
            set(),
            set(),
            [(0, 0)],
            [],
            horizon=25,
            stations=[(3, 1), (2, 1)],
            map_info={"station_access": "delivery_only", "model_version": "math-v4-integrated"},
        )
        rng = random.Random(8121)
        cells = [(x, y) for x in range(4) for y in range(3)]
        for case in range(80):
            vertices = {(rng.randrange(20), rng.choice(cells)) for _ in range(25)}
            start = rng.choice([p for p in cells if p not in scene.stations])
            service = rng.randrange(1, 4)
            paths = [
                cls(scene).leg(
                    start,
                    (3, 1),
                    0,
                    0,
                    vertices,
                    set(),
                    service,
                    delivery_station=(3, 1),
                )
                for cls in (Router, SafeIntervalRouter)
            ]
            self.assertEqual(
                None if paths[0] is None else len(paths[0]),
                None if paths[1] is None else len(paths[1]),
                case,
            )
            if paths[1]:
                self.assertNotIn((2, 1), paths[1])
                self.assertNotIn((3, 1), paths[1][: -service - 1])
                self.assertEqual(paths[1][-service - 1 :], [(3, 1)] * (service + 1))

    def test_delivery_retries_arrival_when_earliest_unload_cannot_exit(self):
        # Minimal routing geometry: one terminal D with a single exit. Earliest
        # unload finishes at 6, but the exit is occupied at 7. Entering D one
        # step later yields a full feasible route without waiting inside D.
        scene = Scenario(
            3,
            2,
            {(2, 0)},
            {(2, 0)},
            [(0, 0)],
            [Task(0, (1, 0), (2, 1), pickup_service=2)],
            horizon=None,
            stations=[(2, 1)],
            map_info={"station_access": "delivery_only", "model_version": "math-v4-integrated"},
        )
        vertices = {(7, (1, 1))}
        for cls in (Router, SafeIntervalRouter):
            with self.subTest(router=cls.__name__):
                path, record, failure, _ = plan_task(
                    scene, cls(scene), scene.tasks[0], 0, scene.homes[0], 0, vertices, set()
                )
                self.assertIsNone(failure)
                self.assertIsNotNone(path)
                self.assertTrue(all((t, point) not in vertices for t, point in enumerate(path)))
                occupied = [t for t, point in enumerate(path) if point == (2, 1)]
                self.assertEqual(
                    occupied, list(range(record["delivery_arrival"], record["delivery_end"] + 1))
                )
                self.assertEqual(path[-1], scene.homes[0])
                self.assertEqual(path[record["delivery_end"] + 1], (1, 1))

    def test_mixed_profile_is_rejected_and_v4_metadata_roundtrip_is_preserved(self):
        scene = Scenario(
            4,
            3,
            {(1, 1)},
            {(1, 1)},
            [(0, 0)],
            [Task(0, (1, 0), (3, 1))],
            horizon=None,
            stations=[(3, 1)],
            map_info={"station_access": "delivery_only"},
        )
        with self.assertRaises(ValueError):
            scene.check()
        scene = generate(task_count=2)
        restored = Scenario.from_dict(scene.to_dict())
        self.assertEqual(restored.stations, scene.stations)
        self.assertEqual(restored.map_info, scene.map_info)

    def test_no_horizon_late_order_completes_and_no_action_terminates(self):
        scene = Scenario(
            5,
            3,
            {(2, 1)},
            {(2, 1)},
            [(0, 0)],
            [Task(0, (1, 1), (4, 1), release=1000)],
            horizon=None,
        ).check()
        result = run_baseline(scene)
        self.assertTrue(result["feasible"])
        self.assertGreater(result["time"], 1000)
        self.assertTrue(validate(scene, result))
        scene.tasks = [replace(scene.tasks[0], release=0)]
        original_advance = Environment.advance

        def bounded_advance(env, *args, **kwargs):
            if env.time > 5:
                raise AssertionError("A stalled unbounded solver must terminate")
            return original_advance(env, *args, **kwargs)

        with patch.object(Environment, "advance", bounded_advance):
            stalled = run_baseline(scene, lambda observation: [])
        self.assertFalse(stalled["feasible"])
        self.assertIn("stall", stalled["reason"])
        self.assertTrue(validate(scene, stalled))


if __name__ == "__main__":
    unittest.main()
