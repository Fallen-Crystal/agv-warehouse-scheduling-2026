import copy
import json
import unittest

from agv.dispatch.greedy import run
from agv.domain import Scenario, Task, example
from agv.evaluation.validation import validate
from agv.experiments.batch import run_batch
from agv.io.scenes import pack_scene, scenario_id, unpack_scene
from agv.simulation import Environment
from agv.web.app import calculate_batch, calculate_loaded, make_html


class ReproTests(unittest.TestCase):
    def test_scene_roundtrip_custom_map_and_hash(self):
        s = example("dynamic", size="medium", seed=4)
        s.tasks = s.tasks[:4]
        s.tasks[0] = Task(
            77, s.tasks[0].pickup, s.tasks[0].delivery, 7, 3, 2, shelf=s.tasks[0].shelf
        )
        original = run(s)
        loaded = unpack_scene(json.loads(json.dumps(pack_scene(s, result=original))))
        self.assertEqual(loaded.to_dict(), s.to_dict())
        self.assertEqual(run(loaded), original)
        self.assertEqual(calculate_loaded(pack_scene(s))["scenario_sha256"], scenario_id(s))
        bad = pack_scene(s)
        bad["scenario"]["tasks"][0]["release"] += 1
        with self.assertRaises(ValueError):
            unpack_scene(bad)
        self.assertEqual(unpack_scene(s.to_dict()).to_dict(), s.to_dict())

    def test_failures_before_pickup_delivery_return(self):
        s = Scenario(5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(10, (1, 1), (4, 1))], 100).check()
        for leg, horizon in [("pickup", 1), ("delivery", 3), ("return", 9)]:
            s.horizon = horizon
            env = Environment(s)
            response = env.assign([(0, 10)])[0]
            self.assertFalse(response["accepted"])
            self.assertEqual(response["failed_leg"], leg)
            r = env.result()
            self.assertEqual(r["diagnostics"]["planning_failure_by_leg"][leg], 1)
            self.assertTrue(validate(s, r))

    def test_unfinished_states_and_return_only(self):
        s = example("dynamic")
        env = Environment(s)
        env.assign([(0, 0)])
        env.advance()
        r = env.result()
        states = {j["status"] for j in r["diagnostics"]["unfinished_tasks"]}
        self.assertEqual(states, {"executing", "waiting_assignment", "not_released"})
        self.assertTrue(validate(s, r))
        s = Scenario(5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(10, (1, 1), (4, 1))], 100).check()
        env = Environment(s)
        env.assign([(0, 10)])
        env.advance(9)
        self.assertEqual(env.result()["diagnostics"]["unfinished_tasks"], [])
        self.assertEqual(env.result()["diagnostics"]["vehicles_away_from_home"], [0])

    def test_invalid_policy_and_action_recorded(self):
        s = example(task_count=2)

        def broken(o):
            raise RuntimeError("demo policy error")

        for policy, reason in [(broken, "policy_error"), (lambda o: [(99, 0)], "invalid_action")]:
            r = run(s, policy)
            self.assertFalse(r["feasible"])
            self.assertEqual(r["reason"], reason)
            self.assertIsNotNone(r["diagnostics"]["execution_error"])
            self.assertTrue(validate(s, r))

    def test_failure_log_corruption_rejected(self):
        s = example(task_count=1)
        s.horizon = 1
        r = run(s)
        bad = copy.deepcopy(r)
        bad["diagnostics"]["planning_failure_count"] += 1
        with self.assertRaises(ValueError):
            validate(s, bad)
        bad = copy.deepcopy(r)
        bad["diagnostics"]["unfinished_tasks"][0]["status"] = "executing"
        with self.assertRaises(ValueError):
            validate(s, bad)

    def test_batch_identical_scenarios_for_policies(self):
        report = run_batch(
            dict(mode="dynamic", arrival="irregular", task_count=4),
            [0, 1],
            policies={
                "a": __import__("agv.dispatch.greedy", fromlist=["*"]).greedy_action,
                "b": __import__("agv.dispatch.greedy", fromlist=["*"]).greedy_action,
            },
        )
        self.assertEqual(len(report["rows"]), 4)
        for a, b in zip(report["entries"][::2], report["entries"][1::2]):
            self.assertEqual(a["scenario_sha256"], b["scenario_sha256"])
            self.assertEqual(a["result"], b["result"])
        self.assertEqual(report["summaries"][0]["success_rate"], 1)
        with self.assertRaises(ValueError):
            run_batch({}, [0, 0])

    def test_batch_failure_exclusion_and_single_sample_std(self):
        report = run_batch(dict(task_count=3, horizon=1), [0, 1])
        s = report["summaries"][0]
        self.assertEqual(s["success_rate"], 0)
        self.assertIsNone(s["mean_flow_time_mean"])
        self.assertIsNone(s["mean_flow_time_std"])
        s = run_batch(dict(task_count=1), [0])["summaries"][0]
        self.assertIsNone(s["mean_flow_time_std"])
        self.assertEqual(s["successes"], 1)

    def test_import_batch_controls_and_limits(self):
        html = make_html()
        for name in (
            "saveScene",
            "sceneFile",
            "loadScene",
            "runBatch",
            "batchSeed",
            "batchCount",
            "failureSummary",
            "exportFailures",
        ):
            self.assertIn('id="' + name + '"', html)
        with self.assertRaises(ValueError):
            calculate_batch(dict(config={}, start_seed=0, count=21))
        report = calculate_batch(dict(config={"task_count": 1}, start_seed=0, count=2))
        self.assertEqual(len(report["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
