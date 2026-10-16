"""Current business contract; historical finite-wait V9 tests remain unchanged."""

import unittest
from copy import deepcopy
from dataclasses import replace

from agv.dispatch.greedy import run
from agv.dispatch.registry import run_named
from agv.domain import Scenario, Task
from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.io.scenes import pack_scene, unpack_scene
from agv.simulation import Environment
from agv.warehouse.mixed import generate, generate_current


def scene(extra=False, end=200):
    s = generate_current(task_count=0, vehicles=1, order_stream_end=end)
    single = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "single")
    s.tasks = [Task(0, None, s.stations[0], pickup_service=2, shelf=tuple(single["position"]))]
    if extra:
        s.tasks.append(replace(s.tasks[0], id=1, release=150))
    return s.check()


class StreamTests(unittest.TestCase):
    def test_same_bay_orders_are_serialized_for_multiple_available_cars(self):
        s = generate_current(task_count=0, vehicles=2)
        row = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "single")
        s.tasks = [
            Task(i, None, s.stations[0], pickup_service=2, shelf=tuple(row["position"]))
            for i in range(3)
        ]
        r = run_named("sipp_stream_dispatch", s.check())
        self.assertTrue(r["feasible"])
        self.assertTrue(validate(s, r))
        for a, other in zip(r["assignments"], r["assignments"][1:]):
            self.assertGreaterEqual(other["assigned_at"], a["pickup_end"])

    def test_boolean_close_timestamp_is_rejected(self):
        s = generate_current(task_count=0, vehicles=1)
        r = run(s)
        r["stream_closed_at"] = False
        with self.assertRaises(ValueError):
            validate(s, r)

    def test_unknown_future_cannot_change_hold_decision(self):
        a, b = Environment(scene()), Environment(scene(True))
        for env in (a, b):
            self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        first_exit = a._records[0]["delivery_end"] + 1
        a.advance(first_exit)
        b.advance(first_exit)
        self.assertEqual(a.observe(), b.observe())
        point = a.observe()["vehicles"][0]["position"]
        a.advance(20)
        b.advance(20)
        self.assertEqual(a.observe(), b.observe())
        self.assertEqual(a.observe()["vehicles"][0]["position"], point)
        self.assertNotEqual(point, a._scenario.homes[0])

    def test_close_is_visible_only_when_it_happens(self):
        env = Environment(scene())
        self.assertFalse(env.observe()["order_stream_closed"])
        self.assertIsNone(env.observe()["stream_closed_at"])
        self.assertNotIn("order_stream_end", env.observe())
        self.assertNotIn("order_stream_end", env.observe()["map"])
        env.advance(200)
        self.assertTrue(env.observe()["order_stream_closed"])
        self.assertEqual(env.observe()["stream_closed_at"], 200)

    def test_finished_batch_waits_then_finally_returns(self):
        s = scene()
        r = run(s)
        self.assertTrue(validate(s, r))
        self.assertLess(r["makespan"], 200)
        self.assertGreater(r["time"], 200)
        self.assertGreater(r["standby_steps"], 100)
        self.assertEqual(r["paths"][0][-1], s.homes[0])
        self.assertEqual(r["stream_closed_at"], 200)

    def test_two_batches_can_reuse_waiting_vehicle(self):
        s = scene(True)
        r = run_named("sipp_stream_dispatch", s)
        self.assertTrue(validate(s, r))
        self.assertTrue(r["feasible"])
        second = r["assignments"][1]["assigned_at"]
        first_end = r["assignments"][0]["delivery_end"]
        self.assertTrue(all(p != s.homes[0] for p in r["paths"][0][first_end : second + 1]))
        self.assertEqual(r["estimated_energy"], 0.05 * r["moves"])

    def test_manual_publisher_must_close_empty_stream(self):
        s = generate_current(task_count=0, vehicles=1, order_stream_end=5)
        env = Environment(s, stream_open=True)
        self.assertFalse(env.done)
        env.advance(5)
        self.assertFalse(env.done)
        env.close_order_stream()
        self.assertTrue(env.done)
        self.assertTrue(validate(s, env.result()))

    def test_cannot_close_before_future_release(self):
        env = Environment(scene(True), stream_open=True)
        with self.assertRaises(ValueError):
            env.close_order_stream()
        self.assertFalse(env.observe()["order_stream_closed"])

    def test_stream_end_types_and_release_bound(self):
        for value in (True, 1.5, -1, 149):
            s = scene(True)
            s.order_stream_end = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                s.check()

    def test_missing_end_is_rejected_for_current_profile(self):
        d = scene().to_dict()
        d.pop("order_stream_end")
        with self.assertRaises(ValueError):
            Scenario.from_dict(d)

    def test_serialization_preserves_new_profile_and_end(self):
        s = scene()
        packed = pack_scene(s)
        self.assertEqual(packed["format"], "agv-scene-v9.1")
        self.assertEqual(unpack_scene(packed).to_dict(), s.to_dict())

    def test_false_final_return_is_rejected(self):
        s = scene()
        r = run(s)
        for collection in ("events", "assignments"):
            r[collection][-1]["return_end"] = r[collection][-1]["delivery_end"]
            r[collection][-1]["return_arrival"] = r[collection][-1]["return_end"]
        with self.assertRaisesRegex(ValueError, "return"):
            validate(s, r)

    def test_false_close_flag_is_rejected(self):
        s = scene()
        r = run(s)
        r["order_stream_closed"] = False
        with self.assertRaisesRegex(ValueError, "stream"):
            validate(s, r)

    def test_extra_fields_and_boolean_layers_are_rejected(self):
        for where in ("root", "catalog", "level"):
            d = scene().to_dict()
            if where == "root":
                d["future_orders"] = []
            elif where == "catalog":
                d["map_info"]["rack_catalog"][0]["future_orders"] = []
            else:
                d["map_info"]["rack_catalog"][0]["levels"] = True
            with self.subTest(where=where), self.assertRaises(ValueError):
                Scenario.from_dict(d)

    def test_malformed_replan_does_not_mutate_state(self):
        env = Environment(scene())
        env.assign([(0, 0)])
        env.advance()
        before = env.observe()
        record = deepcopy(env._records[-1])
        record["pickup_point"] = None
        proposal = dict(
            time=env.time,
            before=(0,),
            after=(0,),
            trials=1,
            plans=deepcopy(env._plans),
            records=[record],
        )
        with self.assertRaises(ValueError):
            env.apply_replan(proposal)
        self.assertEqual(env.observe(), before)

    def test_reference_is_versioned_and_final_distance_is_counted(self):
        s = scene()
        r = score_result(s, run(s))
        reference = reference_context(s)
        self.assertEqual(r["weighted_score"], 1)
        self.assertEqual(reference["policy"], "stream_standby_distance_greedy_service2l_v9_1")
        self.assertEqual(r["model_version"], "mixed-v9.1-reviewed-v1")

    def test_historical_modes_are_not_silently_combined_with_current_rules(self):
        with self.assertRaises(ValueError):
            run_named("sipp_standby8_dispatch", scene())
        with self.assertRaises(ValueError):
            run_named("bcrd_budget", scene())
        with self.assertRaises(ValueError):
            run_named("sipp_stream_dispatch", generate(task_count=0))

    def test_all_sizes_keep_the_same_geometry(self):
        for size in ("medium", "large", "xlarge", "xxlarge"):
            old = generate(size=size, task_count=0)
            new = generate_current(size=size, task_count=0)
            for field in (
                "width",
                "height",
                "blocked",
                "shelves",
                "homes",
                "pickup_zones",
                "transit_only",
                "stations",
            ):
                self.assertEqual(getattr(old, field), getattr(new, field))


if __name__ == "__main__":
    unittest.main()
