import copy
import unittest
from dataclasses import replace

from agv.domain import Scenario, Task
from agv.io.scenes import pack_scene, unpack_scene
from agv.warehouse.mixed import generate


class V9LayoutTests(unittest.TestCase):
    def test_four_sizes_and_orientation_permissions(self):
        for size, dimensions in {
            "medium": (46, 41),
            "large": (62, 47),
            "xlarge": (78, 65),
            "xxlarge": (96, 69),
        }.items():
            scene = generate(size=size, task_count=0, vehicles=2, shelf_layers=8)
            self.assertEqual((scene.width, scene.height), dimensions)
            self.assertTrue(scene.is_v9)
            self.assertFalse(scene.is_v4)
            faces = set()
            for row in scene.map_info["rack_catalog"]:
                x, y = row["position"]
                job = Task(0, None, scene.stations[0], shelf=(x, y))
                candidates = scene.pickup_candidates(job)
                faces.add(row["face"])
                if row["rack_type"] == "single":
                    self.assertEqual(row["levels"], 1)
                    self.assertEqual(candidates, [(x, y - 1), (x, y + 1)])
                else:
                    self.assertEqual(row["levels"], 8)
                    delta = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}[row["face"]]
                    self.assertEqual(candidates, [(x + delta[0], y + delta[1])])
            self.assertEqual(faces, {"B", "U", "D", "L", "R"})

    def test_width_variants_preserve_clearance_and_fixed_facilities(self):
        for work in (2, 3, 4):
            for variant in (0, 1, 2):
                s = generate(task_count=0, work_width=work, layout_variant=variant)
                self.assertEqual(s.map_info["horizontal_vertical_blank_width"], 3)
                self.assertEqual(s.map_info["column_count"], 4)
                self.assertEqual(s.map_info["equipment_count"], 1)
                self.assertFalse(s.pickup_zones & s.transit_only)
                self.assertFalse(set(s.stations) & s.pickup_zones)
                self.assertTrue(all(tuple(p) in s.blocked for p in s.map_info["inbound_ports"]))

    def test_roundtrip_and_profile_envelope_cannot_be_downgraded(self):
        s = generate(task_count=3, vehicles=2, shelf_layers=8)
        envelope = pack_scene(s)
        self.assertEqual(envelope["format"], "agv-scene-v9")
        self.assertEqual(s.to_dict(), unpack_scene(envelope).to_dict())
        for wrong in ("agv-scene-v2", "agv-scene-v4"):
            changed = copy.deepcopy(envelope)
            changed["format"] = wrong
            with self.assertRaises(ValueError):
                unpack_scene(changed)

    def test_unknown_metadata_nested_leaks_and_ambiguous_types_are_rejected(self):
        mutations = [
            lambda d: d["map_info"].update(future_tasks=[]),
            lambda d: d["map_info"]["rack_catalog"][0].update(offline_reference_time=777),
            lambda d: d["map_info"].update(loading_rule="unreviewed"),
            lambda d: d["map_info"].update(rules_version="delivery-only-v999"),
            lambda d: d["map_info"].update(work_width=999),
            lambda d: d["map_info"]["rack_catalog"][0].update(levels=True),
            lambda d: d["map_info"]["rack_pairs"][0]["start"].__setitem__(0, 1.5),
            lambda d: d["map_info"].update(rows=0),
            lambda d: d["map_info"].update(model_version="mixed-v6"),
        ]
        raw = generate(task_count=0).to_dict()
        for mutate in mutations:
            changed = copy.deepcopy(raw)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                Scenario.from_dict(changed)

    def test_actual_bay_layer_limit_is_authoritative(self):
        s = generate(task_count=0, vehicles=1, shelf_layers=8)
        single = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "single")
        paired = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "paired")
        job = Task(
            0,
            None,
            s.stations[0],
            pickup_service=16,
            shelf=tuple(paired["position"]),
            shelf_level=8,
        )
        s.tasks = [job]
        s.check()
        s.tasks = [replace(job, shelf=tuple(single["position"]), shelf_level=2, pickup_service=4)]
        with self.assertRaises(ValueError):
            s.check()

    def test_invalid_generation_parameters_fail_before_build(self):
        for options in (
            {"vehicles": 11},
            {"vehicles": True},
            {"shelf_layers": 2},
            {"shelf_layers": True},
            {"size": "small"},
            {"size": []},
            {"obstacle_layout": "none"},
            {"seed": -1},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                generate(**options)


if __name__ == "__main__":
    unittest.main()
