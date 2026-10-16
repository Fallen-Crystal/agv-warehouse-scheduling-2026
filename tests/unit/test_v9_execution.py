import copy
import unittest
from dataclasses import replace

from agv.dispatch.bcrd import bcrd_action
from agv.domain import Task
from agv.evaluation.validation import validate
from agv.simulation import Environment
from agv.warehouse.mixed import generate


def without_timing(value):
    if isinstance(value, dict):
        return {
            k: without_timing(v)
            for k, v in value.items()
            if k not in ("cpu_seconds", "wall_seconds")
        }
    if isinstance(value, list):
        return [without_timing(v) for v in value]
    return value


class V9ExecutionTests(unittest.TestCase):
    def test_single_bay_can_explicitly_use_either_side(self):
        s = generate(task_count=0, vehicles=1)
        row = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "single")
        s.tasks = [Task(0, None, s.stations[0], pickup_service=2, shelf=tuple(row["position"]))]
        s.check()
        for q in s.pickup_candidates(s.tasks[0]):
            env = Environment(s, router_kind="sipp")
            self.assertTrue(env.assign([(0, 0, q)])[0]["accepted"])
            self.assertEqual(env._records[0]["pickup_point"], q)
            while not env.done:
                env.advance(observe=False)
            self.assertTrue(validate(s, env.result()))

    def test_invalid_side_rejects_whole_input_batch_before_committing(self):
        s = generate(task_count=0, vehicles=2)
        rows = s.map_info["rack_catalog"][:2]
        s.tasks = [
            Task(i, None, s.stations[0], pickup_service=2, shelf=tuple(v["position"]))
            for i, v in enumerate(rows)
        ]
        s.check()
        env = Environment(s, router_kind="sipp")
        before = env.observe()
        with self.assertRaises(ValueError):
            env.assign([(0, 0, s.pickup_candidates(s.tasks[0])[0]), (1, 1, (0, 0))])
        self.assertEqual(before, env.observe())
        self.assertEqual(env._records, [])

    def test_eighth_layer_service_and_same_resource_gates(self):
        s = generate(task_count=0, vehicles=2, shelf_layers=8)
        row = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "paired")
        s.tasks = [
            Task(
                0,
                None,
                s.stations[0],
                pickup_service=16,
                shelf=tuple(row["position"]),
                shelf_level=8,
            )
        ]
        s.tasks.append(replace(s.tasks[0], id=1, shelf_level=1, pickup_service=2))
        s.check()
        env = Environment(s, router_kind="sipp")
        with self.assertRaises(ValueError):
            env.assign([(0, 0), (1, 1)])
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        record = env._records[0]
        self.assertEqual(record["pickup_end"] - record["pickup_arrival"], 16)
        env.advance(record["pickup_end"], observe=False)
        self.assertTrue(next(j for j in env.observe()["pending"] if j["id"] == 1)["dispatchable"])

    def test_bcrd_really_searches_without_reading_v9_future_orders(self):
        s = generate(seed=10, task_count=6, vehicles=2)
        other = copy.deepcopy(s)
        other.tasks.append(replace(other.tasks[-1], id=99, release=800))
        other.check()
        a, b = Environment(s), Environment(other)
        self.assertEqual(a.observe(), b.observe())
        left, right = [], []
        self.assertEqual(
            bcrd_action(a.observe(), diagnostics=left, min_queue_ratio=0),
            bcrd_action(b.observe(), diagnostics=right, min_queue_ratio=0),
        )
        self.assertTrue(left[0]["candidates"])
        self.assertEqual(without_timing(left), without_timing(right))

    def test_bcrd_does_not_silently_use_a_return_only_forecast_for_standby(self):
        env = Environment(generate(task_count=1), idle_hold_steps=16)
        with self.assertRaisesRegex(ValueError, "shadow"):
            bcrd_action(env.observe())


if __name__ == "__main__":
    unittest.main()
