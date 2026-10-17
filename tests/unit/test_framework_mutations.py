"""Bounded deterministic input/trace mutation matrix for the algorithm boundary."""

import math
import unittest
from copy import deepcopy

from agv.dispatch.greedy import run
from agv.domain import Scenario
from agv.evaluation.validation import validate
from agv.warehouse.mixed import generate_current


class FrameworkMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = generate_current(task_count=4, vehicles=2, seed=4702, shelf_layers=8)
        cls.raw = cls.scene.to_dict()
        cls.result = run(cls.scene)

    def test_invalid_scene_field_matrix(self):
        cases = []
        for key in ("width", "height", "horizon", "order_stream_end"):
            for value in (True, "10", 1.5, -1):
                item = deepcopy(self.raw)
                item[key] = value
                cases.append(item)
        for key in ("blocked", "shelves", "homes", "tasks", "stations", "pickup_zones"):
            for value in (None, {}, "bad"):
                item = deepcopy(self.raw)
                item[key] = value
                cases.append(item)
        for key in ("id", "release", "pickup_service", "delivery_service", "shelf_level"):
            for value in (True, "1", 1.5):
                item = deepcopy(self.raw)
                item["tasks"][0][key] = value
                cases.append(item)
        for i, item in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                Scenario.from_dict(item)

    def test_corrupted_execution_field_matrix(self):
        cases = []
        for key in (
            "completed",
            "total_tasks",
            "moves",
            "makespan",
            "service_steps",
            "idle_steps",
            "traffic_wait_steps",
            "response_sample_count",
        ):
            for value in (True, None, "1", math.nan, -1):
                item = deepcopy(self.result)
                item[key] = value
                cases.append(item)
        for key in (
            "assigned_at",
            "pickup_arrival",
            "pickup_end",
            "delivery_arrival",
            "delivery_end",
            "return_arrival",
            "return_end",
        ):
            for value in (True, "1", -1):
                item = deepcopy(self.result)
                item["assignments"][0][key] = value
                cases.append(item)
        for value in (None, [], [False, 0], [0.0, 0], [0, 0, 0]):
            item = deepcopy(self.result)
            item["paths"][0][0] = value
            cases.append(item)
        for i, item in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                validate(self.scene, item)

    def test_json_roundtrip_preserves_audited_result_and_distinct_inventory(self):
        import json

        result = json.loads(json.dumps(self.result))
        self.assertTrue(validate(self.scene, result))
        self.assertTrue(validate(Scenario.from_dict(self.raw), result))
        identities = [r["bay_id"] for r in self.scene.map_info["rack_catalog"]]
        self.assertEqual(len(identities), len(set(identities)))
