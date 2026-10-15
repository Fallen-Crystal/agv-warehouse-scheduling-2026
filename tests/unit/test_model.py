import copy
import json
import unittest

from agv.dispatch.greedy import run
from agv.domain import Scenario, Task, example
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.simulation import Environment


def small(release=0, service=1):
    return Scenario(
        5,
        3,
        {(2, 1)},
        {(2, 1)},
        [(0, 0)],
        [Task(10, (1, 1), (4, 1), release, service, service)],
        100,
    ).check()


class ModelTests(unittest.TestCase):
    def test_arrival_patterns_preserve_locations_and_defaults(self):
        expected = {
            "batch": [0, 0, 0, 15, 15, 15, 30, 30, 30, 45, 45, 45],
            "uniform": list(range(0, 60, 5)),
            "burst": [0] * 6 + [30] * 6,
        }
        reference = example("dynamic", seed=4)
        for demand in ("balanced", "left_hotspot", "right_hotspot", "switching"):
            reference = example("dynamic", seed=4, demand=demand)
            for arrival in ("batch", "uniform", "irregular", "burst"):
                s = example("dynamic", seed=4, demand=demand, arrival=arrival)
                self.assertEqual(
                    [(j.pickup, j.shelf, j.delivery) for j in s.tasks],
                    [(j.pickup, j.shelf, j.delivery) for j in reference.tasks],
                )
                self.assertEqual([j.release for j in s.tasks], sorted(j.release for j in s.tasks))
                if arrival in expected:
                    self.assertEqual([j.release for j in s.tasks], expected[arrival])
                self.assertTrue(
                    all(j.release == 0 for j in example("static", arrival=arrival).tasks)
                )

    def test_dynamic_demand_patterns_run_and_are_reproducible(self):
        for arrival in ("batch", "uniform", "irregular", "burst"):
            for demand in ("balanced", "left_hotspot", "right_hotspot", "switching"):
                s = example("dynamic", arrival=arrival, demand=demand, seed=3)
                self.assertEqual(
                    s.to_dict(),
                    example("dynamic", arrival=arrival, demand=demand, seed=3).to_dict(),
                )
                r = run(s)
                self.assertTrue(r["feasible"])
                self.assertTrue(validate(s, r))

    def test_dynamic_future_data_hidden_for_every_arrival(self):
        for arrival in ("batch", "uniform", "irregular", "burst"):
            s = example("dynamic", arrival=arrival)
            env = Environment(s)
            visible = {j["id"] for j in env.observe()["pending"]}
            self.assertEqual(visible, {j.id for j in s.tasks if j.release == 0})
            future = next(j for j in s.tasks if j.release > 0)
            with self.assertRaises(ValueError):
                env.assign([(0, future.id)])

    def test_scene_configuration(self):
        for size in ("small", "medium", "large"):
            for vehicles in (1, 2, 4, 6, 8):
                s = example(size=size, vehicles=vehicles, task_count=6)
                self.assertEqual(len(s.homes), vehicles)
                r = run(s)
                self.assertTrue(r["feasible"])
                self.assertTrue(validate(s, r))
        for vehicles in (0, 9, 2.5):
            with self.assertRaises(ValueError):
                example(vehicles=vehicles)

    def test_shared_delivery_keeps_pickup_sample(self):
        a = example(delivery_pattern="distributed", seed=9)
        b = example(delivery_pattern="shared", seed=9)
        self.assertEqual(
            [(j.pickup, j.shelf) for j in a.tasks], [(j.pickup, j.shelf) for j in b.tasks]
        )
        self.assertEqual(len({j.delivery for j in b.tasks}), 1)
        r = run(b)
        self.assertTrue(r["feasible"])
        self.assertTrue(validate(b, r))

    def test_single_job_known_answer(self):
        s = small()
        r = run(s)
        self.assertEqual(r["makespan"], 9)
        self.assertEqual(r["time"], 14)
        self.assertEqual(r["moves"], 12)
        self.assertTrue(validate(s, r))

    def test_late_release_no_early_service(self):
        s = small(release=10)
        r = run(s)
        self.assertEqual(r["assignments"][0]["assigned_at"], 10)
        self.assertEqual(r["makespan"], 19)
        self.assertEqual(r["mean_flow_time"], 9)
        self.assertTrue(validate(s, r))

    def test_static_dynamic_locations_identical(self):
        for layout in ("wide", "bottleneck"):
            a, b = example("static", layout, 3), example("dynamic", layout, 3)
            self.assertEqual(
                [(j.pickup, j.shelf, j.delivery) for j in a.tasks],
                [(j.pickup, j.shelf, j.delivery) for j in b.tasks],
            )
            self.assertTrue(all(j.release == 0 for j in a.tasks))

    def test_future_task_hidden_and_observation_copy(self):
        a = Environment(small(release=10))
        b_s = small(release=10)
        b_s.tasks[0] = Task(99, (3, 1), (4, 2), 30)
        b = Environment(b_s)
        self.assertEqual(a.observe(), b.observe())
        self.assertEqual(a.observe()["pending"], [])
        with self.assertRaises(ValueError):
            a.assign([(0, 10)])
        observation = a.observe()
        observation["vehicles"][0]["position"] = (4, 2)
        self.assertEqual(a.observe()["vehicles"][0]["position"], (0, 0))

    def test_busy_duplicate_and_atomic_invalid_batch(self):
        env = Environment(example(task_count=3))
        for pairs in ([(0, 0), (1, 0)], [(0, 0), (0, 1)], [(0, 0), (999, 1)]):
            with self.assertRaises(ValueError):
                env.assign(pairs)
            self.assertEqual(env.result()["assignments"], [])
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        with self.assertRaises(ValueError):
            env.assign([(0, 1)])
        with self.assertRaises(ValueError):
            env.assign([(1, 0)])

    def test_reassign_while_returning(self):
        s = small()
        s.tasks.append(Task(11, (3, 1), (4, 1)))
        env = Environment(s)
        first = env.assign([(0, 10)])[0]
        env.advance(first["planned_delivery_end"])
        self.assertEqual(env.observe()["vehicles"][0]["state"], "returning")
        self.assertTrue(env.assign([(0, 11)])[0]["accepted"])
        while not env.done:
            env.advance()
        r = env.result()
        self.assertEqual(r["assignments"][1]["assigned_at"], r["events"][0]["delivery_end"])
        self.assertTrue(validate(s, r))

    def test_service_duration_and_partial_validation(self):
        s = small(service=3)
        env = Environment(s)
        env.assign([(0, 10)])
        env.advance(4)
        self.assertTrue(validate(s, env.result()))
        while not env.done:
            env.advance()
        r = env.result()
        self.assertEqual(r["service_steps"], 6)
        self.assertTrue(validate(s, r))

    def test_shared_service_point(self):
        s = example(task_count=0)
        s.tasks = [
            Task(0, (2, 4), (11, 2), pickup_service=3),
            Task(1, (2, 4), (11, 2), pickup_service=3),
        ]
        env = Environment(s)
        self.assertTrue(all(r["accepted"] for r in env.assign([(0, 0), (1, 1)])))
        while not env.done:
            env.advance()
        self.assertTrue(validate(s, env.result()))

    def test_reverse_edge_and_service_reservation(self):
        s = small()
        router = Router(s)
        path = router.leg((0, 1), (1, 1), 0, 0, {(0, (1, 1)), (1, (0, 1))}, {(0, (1, 1), (0, 1))})
        self.assertIsNotNone(path)
        self.assertNotIn(path[1], [(0, 1), (1, 1)])
        path = router.leg((0, 1), (1, 1), 0, 0, {(2, (1, 1))}, set(), 2)
        self.assertGreater(len(path) - 3, 2)

    def test_validator_detects_collision_free_edge_swap(self):
        s = Scenario(5, 3, set(), set(), [(0, 0), (1, 0)], [], 100).check()
        r = run(s)
        r["time"] = 2
        r["paths"] = [[(0, 0), (0, 1), (1, 1)], [(1, 0), (1, 1), (0, 1)]]
        # 每一步都在可通行相邻格，且所有整数时刻均无顶点碰撞；仍须拒绝对向交换。
        with self.assertRaisesRegex(ValueError, "Edge swap"):
            validate(s, r)

    def test_irregular_arrivals_and_service_times(self):
        s = example("dynamic", "bottleneck", seed=7, task_count=8)
        releases = [0, 3, 3, 17, 31, 31, 70, 90]
        s.tasks = [
            Task(j.id, j.pickup, j.delivery, releases[i], 1 + i % 3, 1 + i % 2, shelf=j.shelf)
            for i, j in enumerate(s.tasks)
        ]
        r = run(s)
        self.assertTrue(r["feasible"])
        self.assertTrue(validate(s, r))
        self.assertTrue(all(e["assigned_at"] >= releases[e["task_id"]] for e in r["events"]))

    def test_independent_validator_rejects_corruption(self):
        s = example(task_count=3)
        r = run(s)
        for change in ("collision", "service", "release", "metrics", "duplicate"):
            bad = copy.deepcopy(r)
            if change == "collision":
                bad["paths"][1][1] = bad["paths"][0][1]
            if change == "service":
                bad["assignments"][0]["pickup_end"] += 1
            if change == "release":
                bad["assignments"][0]["assigned_at"] = -1
            if change == "metrics":
                bad["mean_flow_time"] += 1
            if change == "duplicate":
                bad["assignments"].append(bad["assignments"][0])
            with self.assertRaises(ValueError):
                validate(s, bad)

    def test_unreachable_and_invalid_map_rejected(self):
        s = small()
        s.blocked |= {(x, 2) for x in range(5)} | {(3, 0), (3, 1)}
        with self.assertRaises(ValueError):
            s.check()
        s = small()
        s.tasks[0] = Task(10, (0, 1), (4, 1))
        with self.assertRaises(ValueError):
            s.check()
        s = small()
        s.tasks[0] = Task(10, (1, 1), (4, 1), -1)
        with self.assertRaises(ValueError):
            s.check()

    def test_horizon_failure_not_success(self):
        s = small()
        s.horizon = 3
        env = Environment(s)
        self.assertFalse(env.assign([(0, 10)])[0]["accepted"])
        self.assertEqual(env.result()["assignments"], [])
        r = run(s)
        self.assertFalse(r["feasible"])
        self.assertEqual(r["reason"], "horizon_exhausted")
        self.assertTrue(validate(s, r))

    def test_json_reset_empty_and_reproducibility(self):
        s = example("dynamic", task_count=4)
        self.assertEqual(
            s.to_dict(), Scenario.from_dict(json.loads(json.dumps(s.to_dict()))).to_dict()
        )
        self.assertEqual(run(s), run(s))
        env = Environment(s)
        original = env.observe()
        env.advance(5)
        self.assertEqual(env.reset(), original)
        empty = example(task_count=0)
        self.assertTrue(run(empty)["feasible"])
        self.assertTrue(validate(empty, run(empty)))

    def test_multiple_seeds_both_modes_layouts(self):
        for seed in range(5):
            for mode in ("static", "dynamic"):
                for layout in ("wide", "bottleneck"):
                    s = example(mode, layout, seed)
                    r = run(s)
                    self.assertTrue(r["feasible"], (seed, mode, layout, r["reason"]))
                    self.assertTrue(validate(s, r))


if __name__ == "__main__":
    unittest.main()
