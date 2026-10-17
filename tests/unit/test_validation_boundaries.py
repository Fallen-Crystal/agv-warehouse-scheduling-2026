"""Counterexamples at the standalone trajectory/score entry points."""

import unittest
from copy import deepcopy

from agv.dispatch.greedy import run
from agv.domain import Scenario, Task
from agv.evaluation.metrics import summarize
from agv.evaluation.objective import score_result, validate_score
from agv.evaluation.validation import validate
from agv.warehouse.mixed import generate_current


def empty_walk():
    s = Scenario(4, 4, set(), set(), [(0, 0)], []).check()
    r = run(s)
    r.pop("diagnostics", None)
    r.update(
        time=2,
        paths=[[(0, 0), (1, 0), (0, 0)]],
        interval_states=[["returning", "returning"]],
        moves=2,
        service_steps=0,
        idle_steps=0,
        traffic_wait_steps=0,
    )
    r.update(summarize(s, r))
    return s, r


def pad(s, r, steps=20):
    r = deepcopy(r)
    r["time"] += steps
    for path, labels, home in zip(r["paths"], r["interval_states"], s.homes):
        path.extend([home] * steps)
        labels.extend(["idle"] * steps)
    r["idle_steps"] += steps * len(s.homes)
    r.update(summarize(s, r))
    return r


class ValidationBoundaries(unittest.TestCase):
    def test_fractional_boolean_float_and_malformed_coordinates_are_rejected(self):
        for point in ((0.5, 0), (True, 0), (1.0, 0), (1,), None, "10", (1, 0, 0)):
            with self.subTest(point=point):
                s, r = empty_walk()
                r["paths"][0][1] = point
                with self.assertRaises(ValueError):
                    validate(s, r)

    def test_mixed_coordinate_edge_swap_is_rejected(self):
        s = Scenario(4, 4, set(), set(), [(0, 0), (2, 1)], []).check()
        r = run(s)
        r.pop("diagnostics", None)
        r.update(
            time=2,
            paths=[[(0, 0), (0, 1), (1, 1)], [(2, 1), [1, 1], [0, 1]]],
            interval_states=[["returning"] * 2] * 2,
            moves=4,
            service_steps=0,
            idle_steps=0,
            traffic_wait_steps=0,
            feasible=False,
        )
        r.update(summarize(s, r))
        with self.assertRaisesRegex(ValueError, "Edge swap"):
            validate(s, r)

    def test_equivalent_list_tuple_hold_is_stationary_and_input_is_untouched(self):
        s, r = empty_walk()
        r["paths"] = [[(0, 0), [0, 0], (0, 0)]]
        r["interval_states"] = [["idle", "idle"]]
        r.update(moves=0, idle_steps=2)
        canonical = deepcopy(r)
        canonical["paths"] = [[(0, 0)] * 3]
        r.update(summarize(s, canonical))
        before = deepcopy(r)
        self.assertTrue(validate(s, r))
        self.assertEqual(r, before)

    def test_empty_scene_with_moves_has_actual_energy_but_no_valid_score(self):
        s, r = empty_walk()
        self.assertTrue(validate(s, r))
        scored = score_result(s, r)
        self.assertEqual(scored["moves"], 2)
        self.assertEqual(scored["estimated_energy"], 0.1)
        self.assertFalse(scored["score_valid"])
        self.assertIsNone(scored["weighted_score"])
        self.assertIsNone(scored["normalized_distance"])
        self.assertTrue(validate_score(s, scored))
        scored["score_valid"], scored["weighted_score"] = True, 0.0
        with self.assertRaises(ValueError):
            validate_score(s, scored)

    def test_empty_stationary_scene_keeps_valid_zero_score(self):
        s = Scenario(4, 4, set(), set(), [(0, 0)], []).check()
        r = score_result(s, run(s))
        self.assertTrue(r["score_valid"])
        self.assertEqual(r["weighted_score"], 0)

    def test_v91_empty_stream_must_end_at_close_without_padding(self):
        s = generate_current(task_count=0, vehicles=2, order_stream_end=5)
        r = run(s)
        self.assertEqual(r["time"], 5)
        self.assertTrue(validate(s, r))
        with self.assertRaisesRegex(ValueError, "terminal|Terminal"):
            validate(s, pad(s, r))

    def test_v91_completed_return_rejects_tail_padding_at_all_score_entry_points(self):
        s = generate_current(task_count=0, vehicles=2, order_stream_end=0)
        row = next(v for v in s.map_info["rack_catalog"] if v["rack_type"] == "single")
        s.tasks = [Task(0, None, s.stations[0], pickup_service=2, shelf=tuple(row["position"]))]
        s.check()
        r = run(s)
        self.assertTrue(validate(s, r))
        forged = pad(s, r)
        for check in (validate, score_result, validate_score):
            with self.subTest(entry=check.__name__):
                with self.assertRaisesRegex(ValueError, "terminal|Terminal"):
                    check(s, forged)


if __name__ == "__main__":
    unittest.main()
