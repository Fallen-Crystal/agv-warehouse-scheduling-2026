"""System audit: public lifecycle, serialization, history and replay contracts."""

import math
import unittest
from copy import deepcopy

from agv.dispatch.greedy import run
from agv.evaluation.validation import validate
from agv.simulation import Environment
from agv.warehouse.mixed import generate_current
from agv.web.app import calculate_loaded
from tests.unit.test_positioning import finish, scene, target_for


class FrameworkContracts(unittest.TestCase):
    def test_batch_advance_stops_at_first_terminal_time_and_finished_advance_is_noop(self):
        s = generate_current(task_count=0, vehicles=2, order_stream_end=5)
        env = Environment(s)
        env.advance(20)
        self.assertEqual(env.time, 5)
        before = env.result()
        env.advance(20)
        self.assertEqual(env.result(), before)
        self.assertTrue(validate(s, before))

    def test_nonempty_step_and_batch_execution_are_identical(self):
        s = scene(release=0, end=0)
        a, b = Environment(s), Environment(s)
        for env in (a, b):
            env.assign([(0, 0)])
        expected = finish(a)
        b.advance(1000, observe=False)
        self.assertEqual(b.result(), expected)
        self.assertTrue(validate(s, b.result()))

    def test_later_positioning_keeps_completed_return_and_past_idle(self):
        s = scene(release=0, end=300)
        env = Environment(s, router_kind="sipp", positioning=True)
        env.assign([(0, 0)])
        returned = env._records[0]["return_end"]
        env.advance(returned + 3, observe=False)
        env.reposition(0, target_for(env))
        result = finish(env)
        self.assertEqual(result["assignments"][0]["return_end"], returned)
        self.assertTrue(validate(s, result))
        self.assertGreaterEqual(result["per_vehicle"][0]["idle_steps"], 3)

    def test_invalid_import_metadata_and_algorithm_use_value_errors(self):
        raw = generate_current(task_count=0, vehicles=1).to_dict()
        for value in (None, [], 0, "mixed-v9.1"):
            item = deepcopy(raw)
            item["map_info"] = value
            with self.subTest(info=value), self.assertRaises(ValueError):
                calculate_loaded(item)
        for value in (None, [], {}, 1, True, "unknown"):
            with self.subTest(algorithm=value), self.assertRaises(ValueError):
                calculate_loaded({"scenario": raw, "config": {"algorithm": value}})

    def test_state_dimensions_vocabulary_and_semantics(self):
        s = scene(release=0, end=0)
        r = run(s)
        cases = []
        item = deepcopy(r)
        item["interval_states"].append([])
        cases.append(item)
        for labels in ([], None, ["idle"] * (r["time"] + 1)):
            item = deepcopy(r)
            item["interval_states"][0] = labels
            cases.append(item)
        for label in ("fake", "unloading", True, None):
            item = deepcopy(r)
            item["interval_states"][0][0] = label
            cases.append(item)
        for i, item in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                validate(s, item)

    def test_boolean_counts_nonfinite_metrics_and_metadata_points_are_rejected(self):
        s = scene(release=0, end=0)
        r = run(s)
        cases = []
        for key in ("completed", "total_tasks", "moves", "makespan"):
            item = deepcopy(r)
            item[key] = bool(item[key])
            cases.append(item)
        for key in ("feasible", "comparison_valid"):
            item = deepcopy(r)
            item[key] = int(item[key])
            cases.append(item)
        for value in (math.inf, math.nan, True, "bad"):
            item = deepcopy(r)
            item["mean_flow_time"] = value
            cases.append(item)
        item = deepcopy(r)
        item["per_vehicle"][0]["assigned_tasks"] = True
        cases.append(item)
        item = deepcopy(r)
        item["task_metrics"][0]["vehicle"] = False
        cases.append(item)
        item = deepcopy(r)
        for collection in ("assignments", "events"):
            point = item[collection][0]["pickup_point"]
            item[collection][0]["pickup_point"] = [float(point[0]), point[1]]
        cases.append(item)
        for i, item in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                validate(s, item)


if __name__ == "__main__":
    unittest.main()
