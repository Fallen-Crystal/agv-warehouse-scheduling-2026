"""Bounded V9 standby: execution safety, accounting and hidden-order invariance."""

import unittest
from copy import deepcopy
from dataclasses import replace

from agv.dispatch.idle import hold_return
from agv.domain import Task
from agv.evaluation.validation import validate
from agv.planning.reservations import reservations
from agv.simulation import Environment
from agv.warehouse.mixed import generate


class V9IdleTests(unittest.TestCase):
    def test_complete_return_event_cannot_be_postdated_or_have_fake_service(self):
        scene = self.fixture()
        result = self.finish(self.assigned(scene))
        for kind in ("postdated", "fake_service", "boolean"):
            forged = deepcopy(result)
            for collection in ("events", "assignments"):
                event = forged[collection][-1]
                if kind == "postdated":
                    event["return_end"] = event["return_arrival"] = result["time"] + 1
                elif kind == "fake_service":
                    event["return_arrival"] -= 1
                else:
                    event["return_arrival"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate(scene, forged)

    def test_reset_cannot_silently_keep_standby_on_another_profile(self):
        from agv.warehouse.layout import generate as generate_v4

        env = self.assigned(self.fixture(), ttl=2)
        before = env.observe()
        with self.assertRaises(ValueError):
            env.reset(generate_v4(task_count=0))
        self.assertEqual(env.observe(), before)

    def fixture(self, *, vehicles=1):
        scene = generate(task_count=0, vehicles=vehicles)
        single = next(v for v in scene.map_info["rack_catalog"] if v["rack_type"] == "single")
        scene.tasks = [
            Task(0, None, scene.stations[-1], pickup_service=2, shelf=tuple(single["position"]))
        ]
        return scene.check()

    def assigned(self, scene, *, ttl=0):
        env = Environment(scene, router_kind="sipp", idle_hold_steps=ttl)
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        return env

    def finish(self, env):
        for _ in range(1000):
            if env.done:
                return env.result()
            env.advance(observe=False)
        self.fail("Finite standby allowance failed to finish its fallback return")

    def test_fixed_ttl_finishes_at_home_with_independently_audited_accounting(self):
        scene = self.fixture()
        base = self.finish(self.assigned(scene))
        env = self.assigned(scene, ttl=2)
        result = self.finish(env)
        self.assertTrue(validate(scene, result))
        self.assertTrue(result["feasible"])
        self.assertEqual(result["paths"][0][-1], scene.homes[0])
        self.assertEqual(env._idle_hold_counts, [2])
        self.assertEqual(result["standby_steps"], 2)
        self.assertEqual(result["interval_states"][0].count("standby"), 2)
        self.assertEqual(result["per_vehicle"][0]["standby_steps"], 2)
        self.assertEqual(result["moves"], base["moves"])
        self.assertEqual(result["makespan"], base["makespan"])
        self.assertEqual(result["time"], base["time"] + 2)
        self.assertEqual(result["idle_steps"], base["idle_steps"] + 2)
        self.assertEqual(result["traffic_wait_steps"], base["traffic_wait_steps"])

    def test_hidden_future_order_cannot_change_standby_or_return_prefix(self):
        scene = self.fixture()
        hidden = deepcopy(scene)
        hidden.tasks.append(replace(hidden.tasks[0], id=1, release=500))
        hidden.check()
        left = self.assigned(scene, ttl=2)
        right = self.assigned(hidden, ttl=2)
        first_exit = left._records[0]["delivery_end"] + 1
        left.advance(first_exit, observe=False)
        right.advance(first_exit, observe=False)
        self.assertEqual(left.observe(), right.observe())
        # Deliberately advance both environments even if the known-only stream
        # finishes: stopping on done would hide an oracle-dependent controller.
        for _ in range(10):
            left.advance(observe=False)
            right.advance(observe=False)
            self.assertEqual(left.observe(), right.observe())
            self.assertEqual(left._paths, right._paths)
        self.assertEqual(left._idle_hold_counts, [2])

    def test_collision_with_reserved_route_rejects_hold_atomically(self):
        scene = self.fixture(vehicles=2)
        env = self.assigned(scene)
        env.advance(env._records[0]["delivery_end"] + 1, observe=False)
        point = env._plans[0][0]
        self.assertIn(point, scene.transit_only)
        vertices, edges = reservations([env._plans[0]], env.time)
        approach = env._router.leg(env._plans[1][0], point, env.time, 1, vertices, edges)
        self.assertIsNotNone(approach)
        depart = env._router.leg(
            point, scene.homes[1], env.time + len(approach) - 1, 1, vertices, edges
        )
        self.assertIsNotNone(depart)
        # Install a safe reservation to isolate the standby mutation check;
        # the route is planned against the original vehicle-zero suffix.
        env._plans[1] = approach + depart[1:]
        before = deepcopy((env.observe(), env._plans, env._records, env._idle_waits))
        with self.assertRaisesRegex(ValueError, "conflicts|edge swap"):
            hold_return(env, 0, len(approach))
        self.assertEqual((env.observe(), env._plans, env._records, env._idle_waits), before)

    def test_station_and_pickup_service_positions_reject_standby(self):
        scene = self.fixture()
        env = self.assigned(scene)
        env.advance(env._records[0]["pickup_arrival"], observe=False)
        self.assertIn(env._plans[0][0], scene.pickup_zones)
        before = env.observe()
        with self.assertRaises(ValueError):
            hold_return(env, 0)
        self.assertEqual(env.observe(), before)
        env.advance(env._records[0]["delivery_end"] - env.time, observe=False)
        self.assertIn(env._plans[0][0], scene.stations)
        self.assertIsNone(env._active[0])
        before = env.observe()
        with self.assertRaisesRegex(ValueError, "ordinary catalog transit"):
            hold_return(env, 0)
        self.assertEqual(env.observe(), before)

    def test_en_route_committed_vehicle_cannot_be_held(self):
        env = self.assigned(self.fixture())
        env.advance(observe=False)
        self.assertIsNotNone(env._active[0])
        before = env.observe()
        with self.assertRaisesRegex(ValueError, "committed task"):
            hold_return(env, 0)
        self.assertEqual(env.observe(), before)

    def test_forged_final_return_at_unload_is_independently_rejected(self):
        scene = self.fixture()
        result = self.finish(self.assigned(scene))
        self.assertTrue(validate(scene, result))
        for records in (result["assignments"], result["events"]):
            records[0]["return_end"] = records[0]["delivery_end"]
            records[0]["return_arrival"] = records[0]["return_end"]
        with self.assertRaisesRegex(ValueError, "Final return event"):
            validate(scene, result)

    def test_corrupted_standby_position_is_independently_rejected(self):
        scene = self.fixture()
        result = self.finish(self.assigned(scene, ttl=2))
        self.assertTrue(validate(scene, result))
        wait = result["idle_waits"][0]
        wait["start"] -= 1  # Includes the actual step leaving D, which is moving.
        with self.assertRaisesRegex(ValueError, "stationary on ordinary transit"):
            validate(scene, result)

    def test_hold_cannot_extend_past_finite_horizon(self):
        scene = self.fixture()
        complete = self.finish(self.assigned(scene))
        scene.horizon = complete["time"]
        env = self.assigned(scene)
        env.advance(env._records[0]["delivery_end"] + 1, observe=False)
        before = env.observe()
        with self.assertRaisesRegex(ValueError, "horizon"):
            hold_return(env, 0)
        self.assertEqual(env.observe(), before)


if __name__ == "__main__":
    unittest.main()
