import copy
import hashlib
import json
import unittest

from agv.dispatch.greedy import run
from agv.domain import Scenario, Task, example
from agv.evaluation.validation import validate
from agv.io.scenes import pack_scene, unpack_scene
from agv.planning.astar import Router
from agv.planning.pickup import plan_task
from agv.simulation import Environment
from agv.web.app import calculate_loaded, make_html


def tiny():
    return Scenario(
        5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(0, None, (4, 2), shelf=(2, 1))], 100
    ).check()


class ShelfTests(unittest.TestCase):
    def test_four_candidates_are_adjacent_free_cells(self):
        s = tiny()
        self.assertEqual(s.pickup_candidates(s.tasks[0]), [(1, 1), (2, 0), (2, 2), (3, 1)])
        r = run(s)
        self.assertTrue(r["feasible"])
        self.assertTrue(validate(s, r))
        self.assertIn(r["events"][0]["pickup_point"], s.pickup_candidates(s.tasks[0]))
        self.assertNotIn((2, 1), r["paths"][0])

    def test_choose_other_side_when_one_side_reserved(self):
        s = tiny()
        vertices = {(t, (1, 1)) for t in range(101)}
        path, record, failed, attempts = plan_task(
            s, Router(s), s.tasks[0], 0, (0, 0), 0, vertices, set()
        )
        self.assertIsNone(failed)
        self.assertNotEqual(record["pickup_point"], (1, 1))
        self.assertEqual(len(attempts), 4)

    def test_blocked_candidate_and_unreachable_shelf_rejected(self):
        s = tiny()
        s.blocked.add((2, 0))
        s.check()
        self.assertNotIn((2, 0), s.pickup_candidates(s.tasks[0]))
        s = tiny()
        s.blocked.update(s.pickup_candidates(s.tasks[0]))
        with self.assertRaises(ValueError):
            s.check()
        s = tiny()
        s.tasks = [Task(0, None, (4, 2), shelf=(1, 1))]
        with self.assertRaises(ValueError):
            s.check()

    def test_same_shelf_different_sides_load_simultaneously(self):
        s = Scenario(
            5,
            3,
            {(2, 1)},
            {(2, 1)},
            [(0, 0), (4, 0)],
            [
                Task(0, None, (0, 2), pickup_service=3, shelf=(2, 1)),
                Task(1, None, (4, 2), pickup_service=3, shelf=(2, 1)),
            ],
            100,
        ).check()
        env = Environment(s)
        self.assertTrue(all(x["accepted"] for x in env.assign([(0, 0), (1, 1)])))
        while not env.done:
            env.advance()
        r = env.result()
        a, b = r["events"]
        self.assertNotEqual(a["pickup_point"], b["pickup_point"])
        self.assertLess(
            max(a["pickup_arrival"], b["pickup_arrival"]), min(a["pickup_end"], b["pickup_end"])
        )
        self.assertTrue(validate(s, r))

    def test_independent_validator_rejects_illegal_stopping_point(self):
        s = tiny()
        r = run(s)
        bad = copy.deepcopy(r)
        bad["assignments"][0]["pickup_point"] = (0, 2)
        with self.assertRaisesRegex(ValueError, "allowed shelf neighbor"):
            validate(s, bad)
        bad = copy.deepcopy(r)
        bad["task_metrics"][0]["shelf_x"] += 1
        with self.assertRaises(ValueError):
            validate(s, bad)

    def test_large_has_four_shelf_columns_and_tasks_use_them(self):
        s = example(size="large", task_count=40, seed=2)
        self.assertEqual({p[0] for p in s.shelves}, {3, 9, 15, 21})
        self.assertEqual({j.shelf[0] for j in s.tasks}, {3, 9, 15, 21})
        for size in ("small", "medium"):
            self.assertEqual(len({p[0] for p in example(size=size).shelves}), 2)

    def test_new_and_legacy_json_import(self):
        s = tiny()
        loaded = unpack_scene(json.loads(json.dumps(pack_scene(s))))
        self.assertEqual(loaded.to_dict(), s.to_dict())
        legacy = dict(
            width=5,
            height=3,
            blocked=[[2, 1]],
            shelves=[[2, 1]],
            homes=[[0, 0]],
            horizon=100,
            tasks=[
                dict(
                    id=0,
                    pickup=[1, 1],
                    delivery=[4, 1],
                    release=0,
                    pickup_service=1,
                    delivery_service=1,
                )
            ],
        )
        digest = hashlib.sha256(
            json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        loaded = unpack_scene(dict(format="agv-scene-v1", scenario=legacy, scenario_sha256=digest))
        r = run(loaded)
        self.assertEqual(r["makespan"], 9)
        self.assertEqual(r["events"][0]["pickup_point"], (1, 1))
        self.assertTrue(validate(loaded, r))

    def test_dynamic_targets_hidden_and_viewer_handles_null_pickup(self):
        s = example("dynamic")
        pending = Environment(s).observe()["pending"]
        self.assertEqual(len(pending), 3)
        self.assertTrue(all(j["pickup"] is None and j["shelf"] is not None for j in pending))
        html = make_html()
        self.assertIn("车辆选择停靠侧", html)
        self.assertIn("targets=targetShelves(s,r,t)", html)
        self.assertIn("当前待取货的货架格 S", html)
        self.assertNotIn("固定取货点 P", html)
        self.assertIn("大仓库有四列货架", html)
        self.assertIn("agv-scene-v2", html)

    def test_page_rejects_old_fixed_pickup_orders(self):
        s = Scenario(5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(0, (1, 1), (4, 2))], 100).check()
        with self.assertRaisesRegex(ValueError, "只接受指定货架格"):
            calculate_loaded(pack_scene(s))
        self.assertTrue(calculate_loaded(pack_scene(tiny()))["result"]["feasible"])


if __name__ == "__main__":
    unittest.main()
