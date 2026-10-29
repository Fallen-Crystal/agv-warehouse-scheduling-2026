import importlib.util
import unittest

if importlib.util.find_spec("ortools") is None:
    raise unittest.SkipTest("Optional exact reference requires pip install -e .[exact]")


from agv.core.objectives import LinearObjective
from agv.evaluation.objectives.linear_f import checked_score
from agv.policy.wepa.coordination import delayed_trip
from agv.policy.wepa.forecast import rollout, snapshot
from agv.policy.wepa.policy import plan_from_prediction
from agv.policy.wepa.proxy import MixedCosts
from agv.policy.wepa.targeted import neighborhoods
from agv.runner.wepa import run
from tests.exact.fixtures import make
from tests.exact.fixtures import new_world as World
from tests.exact.joint import joint_return_graph, tail_path


class CoupledTests(unittest.TestCase):
    def test_targeted_neighbors_keep_all_jobs_and_valid_owners(self):
        w = World(make("layers"))
        w.publish_and_complete()
        v = snapshot(w)
        p, _ = rollout(v)
        order, owners = plan_from_prediction(p, set(v.tasks) - v.assigned)
        costs = MixedCosts(v, p)
        a = neighborhoods(costs, order, owners)
        b = neighborhoods(costs, order, owners)
        self.assertTrue(a)
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), 48)
        self.assertTrue(any(kind == "target_transfer" for _, _, kind in a))
        seen = set()
        for o, x, kind in a:
            self.assertEqual(set(o), set(order))
            self.assertEqual(len(o), len(order))
            self.assertTrue(all(0 <= k < 2 for k in x.values()))
            key = tuple(o), tuple(x[j] for j in o)
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_all_four_arms_have_valid_mixed_and_layer_traces(self):
        obj = LinearObjective(vehicles=2)
        for name in ("cross_out", "mixed", "layers", "mixed_burst"):
            for profile in ("gate", "lns", "coord", "coupled"):
                with self.subTest(name=name, profile=profile):
                    m = make(name)
                    r = run(m, profile, objective=obj)
                    self.assertTrue(checked_score(m, r, obj)["audit"]["valid"])
                    for log in r["search_log"]:
                        if "previews" in log:
                            self.assertLessEqual(log["previews"], 6)
                            self.assertLessEqual(log["proxy_evaluations"], 192)
                    self.assertLessEqual(len(r["coordination_log"]), 4)
                    for log in r["coordination_log"]:
                        if "route_calls" in log:
                            self.assertLessEqual(log["route_calls"], 1100)
                        if log["accepted"]:
                            self.assertLess(log["score"], log["base_score"])

    def test_coordination_is_actually_exercised_and_rejects_worse(self):
        r = run(make("cross_out"), "coord", objective=LinearObjective(vehicles=2))
        logs = r["coordination_log"]
        self.assertTrue(logs)
        self.assertTrue(any("base_score" in l for l in logs))
        self.assertFalse(any(l["accepted"] for l in logs))

    def test_delayed_trip_keeps_assignment_time_and_safe_prefix(self):
        w = World(make("cross_out"))
        w.publish_and_complete()
        j = w.ready()[0]
        p = delayed_trip(w, 0, j, 2)
        self.assertIsNotNone(p)
        path, record = p
        self.assertEqual(path[:3], [w.scene.homes[0]] * 3)
        self.assertEqual(record["assigned_at"], 0)
        self.assertGreaterEqual(record["pickup_arrival"], 2)
        self.assertIsNone(w.table().conflict(path, 0, 0))

    def test_joint_return_moves_and_tail_safety(self):
        m = make()
        s = m["scene"]
        cells, dist, succ = joint_return_graph(s)
        self.assertEqual(dist[tuple(s.homes)], (0, 0))
        self.assertGreater(len(dist), 100)
        for state in sorted(dist)[::17]:
            route = tail_path(state, s, succ)
            self.assertEqual(route[-1], tuple(s.homes))
            self.assertEqual(
                sum(a != b for x, y in zip(route, route[1:]) for a, b in zip(x, y)), dist[state][0]
            )
            for x, y in zip(route, route[1:]):
                self.assertNotEqual(y[0], y[1])
                self.assertNotEqual((x[1], x[0]), y)
                self.assertTrue(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1 for a, b in zip(x, y)))


if __name__ == "__main__":
    unittest.main()
