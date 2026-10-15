"""V4 profile compatibility and adversarial domain-boundary checks."""

import copy
import hashlib
import json
import unittest
from dataclasses import replace

from agv.domain import Scenario, example
from agv.warehouse.layout import generate
from agv.warehouse.rules import dispatch_status


def digest(scenario):
    raw = json.dumps(scenario.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class V4DomainTests(unittest.TestCase):
    def test_legacy_scene_identity_is_preserved(self):
        self.assertEqual(
            digest(example()),
            "3587b51f67b02b6ac4b607b10f6c058f82a0659f227d5d53b4727e3134471355",
        )
        self.assertEqual(
            digest(
                example(
                    mode="dynamic",
                    size="medium",
                    seed=7,
                    vehicles=6,
                    task_count=30,
                    arrival="burst",
                )
            ),
            "33b8ebc6b514176b432ffb158bce862c80e6e660e1c26ac7572b0323eeaaa942",
        )
        self.assertNotIn("shelf_level", example().to_dict()["tasks"][0])
        self.assertEqual(
            set(example().observation_map()), {"width", "height", "blocked", "shelves", "homes"}
        )

    def test_teammate_v4_scene_identity_and_roundtrip(self):
        s = generate(
            mode="dynamic",
            task_count=6,
            vehicles=4,
            size="small",
            arrival="burst",
            obstacle_layout="columns_equipment",
        )
        # Independently calculated from the teammate's unmodified generator.
        self.assertEqual(
            digest(s), "3244fdf84d91027e9fb69a620752a4c94af96a60779e9d445fd3d9f8742ae03f"
        )
        restored = Scenario.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual(s.to_dict(), restored.to_dict())
        self.assertIsNone(restored.horizon)
        self.assertTrue(all(len(s.pickup_candidates(j)) == 1 for j in s.tasks))

    def test_all_scales_obstacles_and_ten_vehicles(self):
        for size in ("small", "medium", "large", "xlarge", "xxlarge"):
            for obstacles in ("none", "columns", "columns_equipment"):
                with self.subTest(size=size, obstacles=obstacles):
                    s = generate(
                        size=size,
                        vehicles=10,
                        task_count=1,
                        obstacle_layout=obstacles,
                        layout_variant=2,
                    )
                    self.assertEqual(len(s.homes), 10)
                    self.assertTrue(s.is_v4)
                    self.assertEqual(Scenario.from_dict(s.to_dict()).to_dict(), s.to_dict())

    def test_arrival_and_layer_streams_are_independent(self):
        reference = generate(mode="dynamic", seed=7, task_count=12)
        for arrival in ("batch", "uniform", "irregular", "burst"):
            s = generate(mode="dynamic", arrival=arrival, seed=7, task_count=12)
            self.assertEqual(
                [(j.shelf, j.delivery, j.shelf_level) for j in s.tasks],
                [(j.shelf, j.delivery, j.shelf_level) for j in reference.tasks],
            )
            self.assertEqual([j.release for j in s.tasks], sorted(j.release for j in s.tasks))
            self.assertTrue(all(j.pickup_service == 2 * j.shelf_level for j in s.tasks))

    def test_observation_has_only_public_static_geometry_and_is_detached(self):
        s = generate(mode="dynamic", arrival="uniform", task_count=10)
        data = s.observation_map()
        raw = json.dumps(data)
        for forbidden in ("tasks", "seed", "normalization_reference", "assigned_at"):
            self.assertNotIn('"' + forbidden + '"', raw)
        geometry = Scenario.from_observation_map(data, horizon=None)
        self.assertEqual(geometry.tasks, [])
        self.assertEqual(geometry.stations, s.stations)
        data["map_info"]["rack_catalog"][0]["position"][0] = -100
        self.assertNotEqual(data["map_info"], s.map_info)

    def test_station_terminal_permission(self):
        s = generate(task_count=1)
        station = s.stations[0]
        adjacent = next(s.neighbors(station))
        self.assertNotIn(station, set(s.travel_neighbors(adjacent)))
        self.assertIn(station, set(s.travel_neighbors(adjacent, delivery_goal=station)))

    def test_missing_profile_or_changed_rules_cannot_silently_downgrade(self):
        original = generate(task_count=1).to_dict()
        mutations = [
            lambda d: d.pop("map_info"),
            lambda d: d["map_info"].pop("model_version"),
            lambda d: d["map_info"].pop("station_access"),
            lambda d: d.update(service_axis="any"),
            lambda d: d["map_info"].update(layer_order="none"),
            lambda d: d["map_info"].update(seed=123),
            lambda d: d["tasks"][0].update(pickup_service=1),
            lambda d: d["tasks"][0].update(shelf_level=True),
        ]
        for mutation in mutations:
            raw = copy.deepcopy(original)
            mutation(raw)
            with self.subTest(raw=raw.get("service_axis")), self.assertRaises(ValueError):
                Scenario.from_dict(raw)

    def test_malformed_input_always_reports_value_error(self):
        original = generate(task_count=1).to_dict()
        mutations = [
            lambda d: d.update(stations=[None]),
            lambda d: d.update(map_info=None),
            lambda d: d.update(pickup_zones=1),
            lambda d: d.update(homes=[True]),
            lambda d: d["map_info"].update(rack_catalog=[None]),
            lambda d: d["map_info"].update(obstacles=[{"kind": [], "cells": []}]),
            lambda d: d["map_info"].update(facility_bands=[None]),
            lambda d: d["map_info"].update(layer_count=True),
            lambda d: d["map_info"].update(equipment_footprint=[True, 3]),
        ]
        for mutation in mutations:
            raw = copy.deepcopy(original)
            mutation(raw)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                Scenario.from_dict(raw)

    def test_layer_gate_does_not_read_future_and_uses_immutable_task_identity(self):
        s = generate(task_count=1)
        low = replace(s.tasks[0], id=0, shelf_level=1, pickup_service=2)
        high = replace(low, id=1, release=10, shelf_level=3, pickup_service=6)
        s.tasks = [low, high]
        self.assertEqual(dispatch_status(s, low, [], set(), 0), (True, None))
        self.assertFalse(dispatch_status(s, low, [], set(), 10)[0])
        self.assertTrue(dispatch_status(s, high, [], set(), 10)[0])
        # Omitted or falsified optional shelf metadata must not bypass the lock.
        for record in (
            {"task_id": 0, "pickup_end": 20},
            {"task_id": 0, "pickup_end": 20, "shelf": (0, 0)},
        ):
            self.assertEqual(
                dispatch_status(s, high, [record], {0}, 10), (False, "same_face_pickup_in_progress")
            )
        self.assertTrue(dispatch_status(s, high, [{"task_id": 0, "pickup_end": 20}], {0}, 20)[0])

    def test_invalid_generation_options_fail(self):
        for options in (
            {"vehicles": True},
            {"vehicles": 11},
            {"horizon": False},
            {"seed": -1},
            {"task_count": True},
            {"size": "unknown"},
            {"shelf_layers": True},
            {"work_width": 1},
            {"aisle_width": 3},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                generate(**options)


if __name__ == "__main__":
    unittest.main()
