import unittest
from copy import deepcopy
from dataclasses import replace

from agv.evaluation.objective import score_result
from agv.evaluation.validation import validate
from agv.planning.joint_meta import search
from agv.planning.joint_orders import JointCosts
from agv.policy.bcrd import fallback
from agv.policy.joint_orders import JointOrderPolicy, OwnedDriver
from agv.policy.routing_contract import RoutingOracle
from agv.registry import SolverSpec
from agv.runner.environment import Environment
from agv.runner.joint_research import run
from agv.runner.run import run as execute
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


class JointOrderTests(unittest.TestCase):
    def test_stale_offer_is_rejected_without_mutating_observation(self):
        s = generate_current(seed=200, vehicles=2, task_count=3, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        oracle = RoutingOracle(obs, world_factory=Environment)
        driver = OwnedDriver(
            [j["id"] for j in obs["pending"]], {j["id"]: 0 for j in obs["pending"]}
        )
        offer = oracle.offer(driver(obs))
        self.assertEqual(offer.resolve(obs), driver(obs))
        changed = deepcopy(obs)
        changed["time"] += 1
        with self.assertRaisesRegex(ValueError, "Stale"):
            offer.resolve(changed)
        self.assertEqual(obs["time"], 0)

    def test_feedback_is_detached_and_budget_failure_is_explicit(self):
        s = generate_current(seed=200, vehicles=2, task_count=3, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        driver = OwnedDriver(
            [j["id"] for j in obs["pending"]], {j["id"]: 0 for j in obs["pending"]}
        )
        oracle = RoutingOracle(obs, world_factory=Environment, max_previews=1)
        response = oracle.evaluate(driver)
        self.assertTrue(response.valid_complete)
        first = response.data
        first["assignments"].clear()
        self.assertTrue(response.data["assignments"])
        with self.assertRaisesRegex(ValueError, "budget"):
            oracle.evaluate(driver)
        failed = RoutingOracle(obs, world_factory=Environment, max_route_calls=0).evaluate(driver)
        self.assertFalse(failed.valid_complete)
        self.assertIn("budget", failed.data["reason"])

    def test_owner_and_priority_do_not_change_task_set(self):
        s = generate_current(seed=201, vehicles=2, task_count=4, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        ids = [j["id"] for j in obs["pending"]]
        owners = {j: i % 2 for i, j in enumerate(ids)}
        a, b = (OwnedDriver(ids, owners, priority=p) for p in ((0, 1), (1, 0)))
        self.assertEqual(set(a(obs)), set(b(obs)))
        self.assertTrue(all(owners[j] == k for k, j in a(obs)))

    def test_all_modes_have_independently_valid_execution(self):
        s = generate_current(seed=202, vehicles=2, task_count=4, mode="static", horizon=None)
        for mode in ("assignment", "priority", "combined", "random", "aco", "pso"):
            r = score_result(s, run(s, mode=mode, candidate_budget=4))
            self.assertTrue(validate(s, r))
            self.assertTrue(r["score_valid"], r.get("diagnostics"))
            self.assertEqual(r["objective_weights"], dict(time=0.5, response=0.3, distance=0.2))
            self.assertTrue(r["joint_search"]["commit_feedback"])

    def test_new_interface_cannot_see_hidden_future(self):
        a = generate_current(seed=203, vehicles=2, task_count=3, mode="static", horizon=None)
        a.tasks = [replace(j, release=0 if j.id == 0 else 80) for j in a.tasks]
        a.order_stream_end = 90
        b = Scenario.from_dict(a.to_dict())
        b.tasks = [j if j.id == 0 else replace(j, id=j.id + 100, release=800) for j in b.tasks]
        b.order_stream_end = 900
        oa, ob = (Environment(s, router_kind="sipp").observe() for s in (a, b))
        pa, pb = (JointOrderPolicy(world_factory=Environment, candidate_budget=2) for _ in range(2))
        self.assertEqual(oa, ob)
        self.assertEqual(pa.action(oa), pb.action(ob))
        self.assertEqual(pa.decisions, pb.decisions)

    def test_real_rejection_invalidates_future_advisory_plan(self):
        s = generate_current(seed=204, vehicles=2, task_count=3, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        policy = JointOrderPolicy(world_factory=Environment, candidate_budget=2)
        pairs = policy.action(obs)
        policy.on_assignment(
            obs,
            [
                dict(vehicle=k, task_id=j, accepted=False, reason="injected_route_failure")
                for k, j in pairs
            ],
            obs,
        )
        self.assertIsNone(policy.driver)
        self.assertTrue(policy.commit_feedback[-1]["rejected"])

    def test_metaheuristics_preserve_permutation_owners_budget_and_seed(self):
        s = generate_current(seed=205, vehicles=2, task_count=4, mode="static", horizon=None)
        obs = Environment(s, router_kind="sipp").observe()
        ids = [j["id"] for j in obs["pending"]]
        owners = {j: i % 2 for i, j in enumerate(ids)}
        for method in ("aco", "pso"):
            args = dict(method=method, seed=1, budget=25)
            first = search(JointCosts(obs, s), ids, owners, **args)
            self.assertEqual(first, search(JointCosts(obs, s), ids, owners, **args))
            self.assertLessEqual(first[1]["unique_evaluations"], 25)
            self.assertGreater(first[1]["unique_evaluations"], 1)
            for sequence, assignment, _ in first[0]:
                self.assertEqual(set(sequence), set(ids))
                self.assertEqual(len(sequence), len(ids))
                self.assertEqual(set(assignment), set(ids))
                self.assertTrue(set(assignment.values()) <= {0, 1})

    def test_assignment_callback_receives_fresh_post_commit_observation(self):
        s = generate_current(seed=206, vehicles=2, task_count=3, mode="static", horizon=None)
        commits = []

        def callback(before, feedback, after):
            for r in feedback:
                if r["accepted"]:
                    k = r["vehicle"]
                    self.assertTrue(before["vehicles"][k]["available"])
                    self.assertFalse(after["vehicles"][k]["available"])
                    self.assertEqual(after["vehicles"][k]["task_id"], r["task_id"])
                    commits.append(r)

        r = execute(SolverSpec(router="sipp"), s, action=fallback, on_assignment=callback)
        self.assertEqual(r["completed"], 3)
        self.assertEqual(len(commits), 3)


if __name__ == "__main__":
    unittest.main()
