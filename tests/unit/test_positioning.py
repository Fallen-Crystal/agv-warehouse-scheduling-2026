"""Behavior contracts for opt-in positioning and its independent audit."""

import random
import unittest
from copy import deepcopy
from dataclasses import replace

from agv.dispatch.positioning import PositioningPolicy, articulation_points, waiting_candidates
from agv.dispatch.stream import run as run_stream
from agv.domain import Scenario, Task
from agv.evaluation.validation import validate
from agv.planning.reservations import PlanReservations
from agv.simulation import Environment
from agv.warehouse.mixed import generate_current


def scene(*, vehicles=1, release=None, extra=False, end=200):
    result = generate_current(task_count=0, vehicles=vehicles, order_stream_end=end)
    row = max(
        (v for v in result.map_info["rack_catalog"] if v["rack_type"] == "single"),
        key=lambda v: tuple(v["position"]),
    )
    if release is not None:
        result.tasks = [
            Task(
                0,
                None,
                result.stations[-1],
                release=release,
                pickup_service=2,
                shelf=tuple(row["position"]),
            )
        ]
        if extra:
            result.tasks.append(replace(result.tasks[0], id=1, release=180))
    return result.check()


def target_for(env, vehicle=0):
    candidates = waiting_candidates(env._scenario)
    return max(
        candidates,
        key=lambda p: (env._router.distance(env._plans[vehicle][0], p, vehicle), p),
    )


def snapshot(env):
    return deepcopy(
        (
            env.observe(),
            env._plans,
            env._records,
            env._active,
            env._position_events,
            env._idle_waits,
        )
    )


def finish(env):
    for _ in range(1000):
        if env.done:
            return env.result()
        env.advance(observe=False)
    raise AssertionError("Positioning did not finish its safe home return")


def brute_conflict(plans, starts, candidate, start, vehicle):
    """Old full-suffix scan, extended by stationary final occupancy."""
    end = max([start + len(candidate) - 1] + [t + len(p) - 1 for p, t in zip(plans, starts)])

    def position(path, origin, time):
        return path[min(time - origin, len(path) - 1)]

    for time in range(start, end + 2):
        current = position(candidate, start, time)
        for peer, (path, origin) in enumerate(zip(plans, starts)):
            if peer == vehicle:
                continue
            other = position(path, origin, time)
            if current == other:
                return True
            if time > start:
                if (
                    position(candidate, start, time - 1) == other
                    and position(path, origin, time - 1) == current
                ):
                    return True
    return False


class ReservationIndexTests(unittest.TestCase):
    def test_mixed_multistep_holds_advance_and_replacements_match_materialized_routes(self):
        rng = random.Random(20261018)

        def walk(start=None):
            path = [start if start is not None else (rng.randrange(5), rng.randrange(5))]
            for _ in range(rng.randrange(1, 12)):
                x, y = path[-1]
                path.append(rng.choice([(x, y), (x, y), (x + 1, y), (x - 1, y), (x, y + 1)]))
            return path

        plans, now, held_until = [walk() for _ in range(4)], 0, [0] * 4
        index = PlanReservations(plans, now)
        for _ in range(200):
            vehicle, operation = rng.randrange(4), rng.randrange(3)
            if operation == 0 and now >= held_until[vehicle]:
                steps = rng.randrange(1, 6)
                plans[vehicle] = [plans[vehicle][0]] * steps + plans[vehicle]
                index.hold(vehicle, now, steps)
                held_until[vehicle] = now + steps
            elif operation == 1:
                plans[vehicle] = walk(plans[vehicle][0])
                index.replace(vehicle, plans[vehicle], now)
                held_until[vehicle] = now
            else:
                steps = rng.randrange(1, 5)
                plans = [path[min(steps, len(path) - 1) :] for path in plans]
                now += steps
            for peer in range(4):
                for offset in (0, 1, 6, 20):
                    self.assertEqual(
                        index.at(peer, now + offset), plans[peer][min(offset, len(plans[peer]) - 1)]
                    )
            for _ in range(3):
                query = rng.randrange(4)
                proposal = walk(plans[query][0] if rng.randrange(2) else None)
                self.assertEqual(
                    index.conflict(proposal, now, query) is not None,
                    brute_conflict(plans, [now] * 4, proposal, now, query),
                )

    def test_reverse_edge_and_stationary_tails_are_reserved(self):
        index = PlanReservations([[(0, 0), (1, 0)], [(3, 0)]], 0)
        self.assertEqual(index.conflict([(1, 0), (0, 0)], 0, 1), "edge")
        self.assertEqual(index.conflict([(2, 0), (1, 0)], 10, 1), "vertex")
        # The proposed path ends first; a later peer visit still conflicts with
        # its indefinite final occupancy, even with no simultaneous finite step.
        index.replace(0, [(0, 0), (0, 1), (1, 1), (2, 1)], 0)
        self.assertEqual(index.conflict([(3, 1), (2, 1)], 0, 1), "vertex")

    def test_random_replacements_match_full_suffix_scan(self):
        rng = random.Random(20261017)

        def walk():
            path = [(rng.randrange(5), rng.randrange(5))]
            for _ in range(rng.randrange(1, 12)):
                x, y = path[-1]
                path.append(rng.choice([(x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]))
            return path

        for _ in range(30):
            plans, starts = [walk() for _ in range(4)], [0] * 4
            index = PlanReservations(plans, 0)
            for now in range(6):
                vehicle = rng.randrange(4)
                candidate = walk()
                self.assertEqual(
                    index.conflict(candidate, now, vehicle) is not None,
                    brute_conflict(plans, starts, candidate, now, vehicle),
                )
                plans[vehicle], starts[vehicle] = candidate, now
                index.replace(vehicle, candidate, now)
                # Compare another query after mutation, exercising removal of
                # old vertex, reverse-edge and final-tail reservations.
                other = (vehicle + 1) % 4
                proposal = walk()
                self.assertEqual(
                    index.conflict(proposal, now, other) is not None,
                    brute_conflict(plans, starts, proposal, now, other),
                )


class PositioningTests(unittest.TestCase):
    def test_cached_public_geometry_is_detached_and_reset_rebuilds_it(self):
        original = scene(vehicles=2)
        original_data = deepcopy(original.to_dict())
        env = Environment(original, positioning=True)
        before = env.observe()
        changed = env.observe()
        changed["map"]["blocked"].clear()
        changed["map"]["homes"].append((99, 99))
        changed["map"]["map_info"]["rack_catalog"][0]["bay_id"] = "corrupted"
        changed["map"]["map_info"]["model_version"] = "corrupted"
        changed["map"]["width"] = 0
        self.assertEqual(env.observe(), before)
        self.assertEqual(original.to_dict(), original_data)
        fresh = generate_current(size="large", task_count=0, vehicles=2, order_stream_end=200)
        env.reset(fresh)
        self.assertEqual(env.observe()["map"], fresh.observation_map())
        self.assertNotEqual(env.observe()["map"]["width"], before["map"]["width"])

    def test_real_sparse_stream_uses_positioning_then_returns_home(self):
        s = generate_current(mode="dynamic", arrival="uniform", task_count=4, vehicles=2, seed=10)
        s.tasks = [replace(task, release=task.release * 20) for task in s.tasks]
        s.order_stream_end *= 20
        result = run_stream(s.check(), positioning=True)
        self.assertTrue(result["feasible"])
        self.assertTrue(validate(s, result))
        self.assertTrue(result["positioning_events"])
        self.assertTrue(
            any(tuple(event["target"]) not in s.homes for event in result["positioning_events"])
        )
        self.assertEqual([path[-1] for path in result["paths"]], s.homes)

    def test_default_environment_does_not_enable_repositioning(self):
        env = Environment(scene())
        before = snapshot(env)
        with self.assertRaisesRegex(ValueError, "opt-in"):
            env.reposition(0, target_for(env))
        self.assertEqual(snapshot(env), before)

    def test_home_vehicle_can_position_before_its_first_assignment(self):
        s = scene()
        env = Environment(s, router_kind="sipp", positioning=True)
        target = target_for(env)
        event = env.reposition(0, target)
        self.assertEqual(env.observe()["positioning_targets"][0]["target"], target)
        self.assertEqual(env._records, [])
        env.advance(event["arrival"], observe=False)
        self.assertEqual(env.observe()["vehicles"][0]["position"], target)
        env.advance(4, observe=False)
        self.assertEqual(env.observe()["vehicles"][0]["position"], target)
        result = finish(env)
        self.assertTrue(result["feasible"])
        self.assertTrue(validate(s, result))
        self.assertEqual(result["paths"][0][-1], s.homes[0])
        self.assertGreater(result["standby_steps"], 0)
        self.assertGreater(result["empty_moves"], 0)

    def test_already_home_request_cannot_rewrite_actual_return_time(self):
        s = scene(release=0, end=300)
        env = Environment(s, router_kind="sipp", positioning=True)
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        actual_return = env._records[0]["return_end"]
        env.advance(actual_return + 2, observe=False)
        self.assertEqual(env.observe()["vehicles"][0]["position"], s.homes[0])
        before = snapshot(env)
        with self.assertRaisesRegex(ValueError, "already at home"):
            env.reposition(0, s.homes[0])
        self.assertEqual(snapshot(env), before)
        result = finish(env)
        self.assertEqual(result["events"][0]["return_end"], actual_return)
        self.assertTrue(validate(s, result))

    def test_new_order_interrupts_an_inflight_positioning_route(self):
        s = scene(release=5)
        env = Environment(s, router_kind="sipp", positioning=True)
        event = env.reposition(0, target_for(env))
        self.assertGreater(event["arrival"], 5)
        env.advance(5, observe=False)
        current = env.observe()["vehicles"][0]["position"]
        self.assertNotEqual(current, s.homes[0])
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        self.assertIsNone(env.observe()["positioning_targets"][0])
        self.assertEqual(env._plans[0][0], current)
        result = finish(env)
        self.assertTrue(validate(s, result))
        self.assertTrue(result["feasible"])

    def test_same_tick_new_order_can_interrupt_without_an_executed_positioning_step(self):
        s = scene(release=0)
        env = Environment(s, router_kind="sipp", positioning=True)
        env.reposition(0, target_for(env))
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        result = finish(env)
        self.assertTrue(validate(s, result))

    def test_close_during_active_order_returns_all_vehicles_after_delivery(self):
        s = scene(vehicles=2, release=5, end=5)
        env = Environment(s, router_kind="sipp", positioning=True)
        env.reposition(0, target_for(env))
        env.reposition(1, min(waiting_candidates(s)))
        env.advance(5, observe=False)
        self.assertTrue(env.observe()["order_stream_closed"])
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        result = finish(env)
        self.assertTrue(result["feasible"])
        self.assertTrue(validate(s, result))
        self.assertEqual([path[-1] for path in result["paths"]], s.homes)
        with self.assertRaises(ValueError):
            env.reposition(0, target_for(env))

    def test_invalid_or_busy_target_rejection_preserves_routes_and_records(self):
        s = scene(vehicles=2, release=0)
        env = Environment(s, router_kind="sipp", positioning=True)
        for target in (next(iter(s.pickup_zones)), s.stations[0], s.homes[1], (True, 1)):
            before = snapshot(env)
            with self.subTest(target=target), self.assertRaises(ValueError):
                env.reposition(0, target)
            self.assertEqual(snapshot(env), before)
        env.assign([(0, 0)])
        before = snapshot(env)
        with self.assertRaisesRegex(ValueError, "committed"):
            env.reposition(0, target_for(env))
        self.assertEqual(snapshot(env), before)

    def test_reserved_stationary_tail_rejects_reposition_atomically(self):
        env = Environment(scene(vehicles=2), router_kind="sipp", positioning=True)
        target = target_for(env)
        # Isolate a parked peer's reservation, including its stationary tail.
        # No execution of the injected peer suffix is performed by this test.
        peer_path = env._router.leg(env._plans[1][0], target, 0, 1, set(), set())
        self.assertIsNotNone(peer_path)
        env._replace_plan(1, peer_path)
        before = snapshot(env)
        with self.assertRaisesRegex(ValueError, "safe|conflicts"):
            env.reposition(0, target)
        self.assertEqual(snapshot(env), before)

    def test_hidden_future_does_not_change_observation_or_positioning_action(self):
        left, right = (
            Environment(scene(vehicles=2, release=0, extra=extra), positioning=True)
            for extra in (False, True)
        )
        for env in (left, right):
            env.assign([(0, 0)])
        self.assertEqual(left.observe(), right.observe())
        policies = [PositioningPolicy(env.observe(), strength=256) for env in (left, right)]
        actions = [policy.action(env.observe()) for policy, env in zip(policies, (left, right))]
        self.assertEqual(actions[0], actions[1])
        self.assertTrue(any(vehicle == 1 for vehicle, _ in actions[0]))
        for env, action in zip((left, right), actions):
            for vehicle, target in action:
                env.reposition(vehicle, target)
            env.advance(10, observe=False)
        self.assertEqual(left.observe(), right.observe())
        self.assertEqual(policies[0].action(left.observe()), policies[1].action(right.observe()))

    def test_policy_never_uses_another_vehicle_home_as_a_target(self):
        s = scene(vehicles=2, release=0)
        point = min(
            s.map_info["rack_catalog"],
            key=lambda row: (
                abs(row["position"][0] - s.homes[1][0]) + abs(row["position"][1] - s.homes[1][1])
            ),
        )
        s.tasks = [replace(s.tasks[0], shelf=tuple(point["position"]))]
        env = Environment(s.check(), positioning=True)
        env.assign([(1, 0)])
        policy = PositioningPolicy(env.observe(), strength=1024)
        # With every ordinary candidate excluded, the only alternatives are
        # Home cells. Demand near peer H must not make that forbidden goal win.
        policy.candidates = ()
        self.assertEqual(policy.action(env.observe()), [])

    def test_articulation_and_narrow_candidates_are_excluded(self):
        free = {(x, y) for x in (0, 1, 3, 4) for y in (0, 1, 2)} | {(2, 1)}
        graph = {
            p: tuple(q for q in free if abs(p[0] - q[0]) + abs(p[1] - q[1]) == 1) for p in free
        }
        self.assertEqual(articulation_points(graph), {(1, 1), (2, 1), (3, 1)})
        s = Scenario(
            5,
            3,
            {(x, y) for x in range(5) for y in range(3)} - free,
            set(),
            [],
            [],
            transit_only=free,
            pickup_zones={(4, 0)},
        )
        candidates = waiting_candidates(s)
        self.assertIn((0, 1), candidates)
        self.assertNotIn((1, 1), candidates)  # Degree four, but a cut vertex.
        self.assertNotIn((2, 1), candidates)  # Degree two corridor.
        self.assertNotIn((4, 1), candidates)  # Adjacent to a service cell.
        self.assertTrue(all(len(graph[p]) > 2 for p in candidates))

    def test_forged_held_timing_is_independently_rejected(self):
        s = scene()
        env = Environment(s, router_kind="sipp", positioning=True)
        env.reposition(0, target_for(env))
        result = finish(env)
        self.assertTrue(validate(s, result))
        for kind in ("arrival", "postdated_return", "moving_hold"):
            forged = deepcopy(result)
            if kind == "arrival":
                forged["positioning_events"][0]["arrival"] -= 1
            elif kind == "postdated_return":
                forged["positioning_events"][0]["return_end"] = result["time"] + 1
            else:
                forged["idle_waits"][0]["start"] -= 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate(s, forged)


if __name__ == "__main__":
    unittest.main()
