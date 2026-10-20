"""Contracts across snapshots, observations, commands, and incremental state.

These tests exercise the architectural seams against independently materialized
routes and real task execution, rather than reproducing kernel internals.
"""

import random
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from agv.runner.environment import Environment
from agv.warehouse.mixed import generate, generate_current
from agv.world.itinerary import Itinerary
from agv.world.reservations import ReservationTable, reservations
from agv.world.tasks import TaskState


def stream_scene(*, vehicles=2):
    scene = generate_current(seed=10, task_count=2, vehicles=vehicles, order_stream_end=8)
    scene.tasks = [replace(scene.tasks[0], release=0), replace(scene.tasks[1], release=4)]
    return scene.check()


def execution_footprint(world):
    """Command state, excluding diagnostic counters for attempted route searches."""
    detached = world.snapshot()
    trace = detached.export_trace()
    trace.pop("routing_stats")
    index = detached.plan_reservations()
    return (
        detached.observe(),
        trace,
        [list(path) for path in detached._plans],
        detached.tasks.assigned,
        detached.tasks.active,
        detached._position_targets,
        detached._idle_hold_counts,
        index.version,
        index.routes,
        dict(index.users),
    )


def position(path, origin, time):
    return path[min(max(time - origin, 0), len(path) - 1)]


def materialize(paths, origins, start, excluded):
    """Reference definition: crop each route now, retaining its current tail."""
    vertices, edges = set(), set()
    for vehicle, (path, origin) in enumerate(zip(paths, origins)):
        if vehicle == excluded:
            continue
        end = max(start, origin + len(path) - 1)
        for time in range(start, end + 1):
            point = position(path, origin, time)
            vertices.add((time, point))
            if time < end:
                edges.add((time, point, position(path, origin, time + 1)))
    timeline = {}
    for time, point in vertices:
        timeline.setdefault(point, set()).add(time)
    return vertices, edges, {point: sorted(times) for point, times in timeline.items()}


class ItineraryContractTests(unittest.TestCase):
    def test_long_route_cursor_keeps_immutable_storage_and_terminal_position(self):
        incoming = [[step, 0] for step in range(10000)]
        original = Itinerary(incoming)
        incoming[0][0] = -99
        current = original
        for _ in range(3000):
            current = current.advance()
        self.assertIs(current.cells, original.cells)
        self.assertEqual(original[0], (0, 0))
        self.assertEqual(current[0], (3000, 0))
        self.assertEqual(len(current), 7000)
        self.assertEqual(current[-1], (9999, 0))
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            current.cursor = 0
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            current.cells = ()
        with self.assertRaises(TypeError):
            current.cells[0][0] = -1
        tail = Itinerary(original, len(original) - 1)
        self.assertEqual(list(tail.advance()), [(9999, 0)])
        self.assertEqual(tail.cursor, 9999)

    def test_snapshot_shares_only_immutable_route_and_static_geometry(self):
        world = Environment(stream_scene(), router_kind="sipp", stream_open=True)
        world.assign([(0, 0)])
        clone = world.snapshot()
        self.assertIs(clone._plans[0], world._plans[0])
        self.assertIs(clone._plans[0].cells, world._plans[0].cells)
        self.assertIs(clone.observe_view()["map"], world.observe_view()["map"])
        original_position = world.observe()["vehicles"][0]["position"]
        clone.tick(1, observe=False)
        self.assertEqual(world.time, 0)
        self.assertEqual(world.observe()["vehicles"][0]["position"], original_position)
        self.assertEqual(clone.time, 1)
        self.assertIs(clone._plans[0].cells, world._plans[0].cells)
        self.assertIsNot(clone._plans[0], world._plans[0])


class WorldIsolationTests(unittest.TestCase):
    def test_snapshot_detaches_records_active_index_and_publisher_state(self):
        world = Environment(stream_scene(), router_kind="sipp", stream_open=True)
        world.assign([(0, 0)])
        original_index = world.plan_reservations()
        before = execution_footprint(world)
        clone = world.snapshot()
        self.assertIsNot(clone.tasks, world.tasks)
        self.assertIsNot(clone.tasks.records, world.tasks.records)
        self.assertIsNot(clone.tasks.assigned, world.tasks.assigned)
        self.assertIsNot(clone.tasks.active, world.tasks.active)
        self.assertIs(clone.tasks.active[0], clone.tasks.records[0])
        self.assertIsNot(clone.tasks.active[0], world.tasks.active[0])
        self.assertIsNot(clone.plan_reservations(), original_index)
        clone.tasks.records[0]["return_end"] += 2
        clone.tasks.active[0]["pickup_point"] = (-1, -1)
        clone.tasks.assigned.add(1)
        clone.plan_reservations().hold(0, clone.time, 2)
        clone.tick(8, observe=False)
        clone.close_order_stream()
        self.assertTrue(clone.orders.closed)
        self.assertEqual(set(clone.orders.released_jobs), {0, 1})
        self.assertFalse(world.orders.closed)
        self.assertEqual(set(world.orders.released_jobs), {0})
        self.assertEqual(execution_footprint(world), before)

    def test_readonly_observations_share_geometry_and_freeze_every_container(self):
        world = Environment(stream_scene(), router_kind="sipp", stream_open=True)
        view = world.observe_view()
        self.assertIs(view["map"], world.observe_view()["map"])
        containers = []

        def visit(value):
            if isinstance(value, dict):
                containers.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, (tuple, list)):
                if isinstance(value, list):
                    containers.append(value)
                for child in value:
                    visit(child)

        visit(view._values)
        self.assertGreater(len(containers), 100)
        for value in containers:
            with self.subTest(container=type(value).__name__), self.assertRaises(TypeError):
                value.update({"unexpected": True}) if isinstance(value, dict) else value.append(
                    None
                )
        with self.assertRaises(TypeError):
            view["time"] = 100
        world.assign([(0, 0)])
        world.tick(4, observe=False)
        self.assertEqual(view["time"], 0)
        self.assertEqual([job["id"] for job in view["pending"]], [0])
        self.assertTrue(view["vehicles"][0]["available"])
        self.assertEqual([job["id"] for job in world.observe_view()["pending"]], [1])
        self.assertIs(view["map"], world.observe_view()["map"])

    def test_legacy_observation_and_deepcopy_are_mutable_detached_json(self):
        world = Environment(stream_scene(), router_kind="sipp", stream_open=True)
        expected = world.observe()
        for editable in (world.observe(), deepcopy(world.observe_view())):
            editable["map"]["map_info"]["rack_catalog"][0]["position"][0] = -1
            editable["map"]["blocked"].clear()
            editable["map"]["homes"].append((-1, -1))
            editable["pending"][0]["id"] = 999
            editable["vehicles"][0]["return_path"].clear()
            self.assertEqual(world.observe(), expected)


class TaskLifecycleTests(unittest.TestCase):
    def test_taskbook_boundaries_match_real_publisher_service_and_vehicle_state(self):
        scene = generate_current(seed=10, task_count=1, vehicles=1, order_stream_end=3)
        scene.tasks = [replace(scene.tasks[0], release=3)]
        world = Environment(scene.check(), router_kind="sipp")
        self.assertEqual(world.tasks.state(0, world.time), TaskState.UNRELEASED)
        self.assertEqual(world.observe()["pending"], [])
        world.tick(3, observe=False)
        self.assertEqual(world.tasks.state(0, world.time), TaskState.PENDING)
        self.assertEqual([job["id"] for job in world.observe()["pending"]], [0])
        self.assertTrue(world.assign([(0, 0)])[0]["accepted"])
        record = deepcopy(world.tasks.records[0])
        boundaries = [
            (world.time, TaskState.ASSIGNED, "to_pickup"),
            (record["pickup_arrival"], TaskState.LOADING, "loading"),
            (record["pickup_end"], TaskState.CARRYING, "to_delivery"),
            (record["delivery_arrival"], TaskState.UNLOADING, "unloading"),
            (record["delivery_end"], TaskState.DONE, "returning"),
        ]
        for time, task_state, vehicle_state in boundaries:
            if time > world.time:
                world.tick(time - world.time, observe=False)
            with self.subTest(time=time, state=task_state):
                self.assertEqual(world.tasks.state(0, time), task_state)
                self.assertEqual(world.observe()["vehicles"][0]["state"], vehicle_state)
                self.assertEqual(world.tasks.active[0] is None, task_state == TaskState.DONE)
        world.tick(record["return_end"] - world.time, observe=False)
        self.assertTrue(world.done)
        self.assertEqual(world.tasks.state(0, world.time), TaskState.DONE)


class ReservationViewContractTests(unittest.TestCase):
    def test_late_start_retains_current_stationary_tail_but_no_infinite_future(self):
        table = ReservationTable([[(0, 0)], [(2, 0), (2, 1)]], 0)
        vertices, edges = table.view_excluding(1, 3)
        self.assertEqual(set(vertices), {(3, (0, 0))})
        self.assertIn((3, (0, 0)), vertices)
        self.assertNotIn((2, (0, 0)), vertices)
        self.assertNotIn((4, (0, 0)), vertices)
        self.assertEqual(vertices.timeline(), {(0, 0): [3]})
        self.assertEqual(set(edges), set())

    def test_random_holds_replacements_views_match_independent_current_suffixes(self):
        rng = random.Random(20261020)

        def walk(start):
            path = [start]
            for _ in range(rng.randrange(3, 18)):
                x, y = path[-1]
                dx, dy = rng.choice(((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)))
                path.append((max(0, min(4, x + dx)), max(0, min(4, y + dy))))
            return path

        paths = [walk((vehicle, 0)) for vehicle in range(4)]
        origins = [0] * 4
        table = ReservationTable(paths, 0)
        now = 0
        for revision in range(50):
            now += rng.randrange(3)
            excluded = rng.choice((None, 0, 1, 2, 3))
            vertices, edges = table.view_excluding(excluded, now)
            vertices.timeline()  # Populate cache before mutating its backing table.
            vehicle = rng.randrange(4)
            end = max(now, origins[vehicle] + len(paths[vehicle]) - 1)
            remaining = [position(paths[vehicle], origins[vehicle], t) for t in range(now, end + 1)]
            if revision % 2 and len(remaining) > 1:
                steps = rng.randint(1, 3)
                table.hold(vehicle, now, steps)
                paths[vehicle] = [remaining[0]] * steps + remaining
            else:
                paths[vehicle] = walk(remaining[0])
                table.replace(vehicle, paths[vehicle], now)
            origins[vehicle] = now
            expected_v, expected_e, expected_t = materialize(paths, origins, now, excluded)
            with self.subTest(revision=revision, time=now, excluded=excluded):
                self.assertEqual(set(vertices), expected_v)
                self.assertEqual(set(edges), expected_e)
                self.assertEqual(vertices.timeline(), expected_t)
                current_paths = [
                    [
                        position(path, origin, time)
                        for time in range(now, max(now, origin + len(path) - 1) + 1)
                    ]
                    for peer, (path, origin) in enumerate(zip(paths, origins))
                    if peer != excluded
                ]
                old_v, old_e = reservations(current_paths, now)
                self.assertEqual(set(old_v), expected_v)
                self.assertEqual(old_e, expected_e)
                for time in range(now - 1, max(t for t, _ in expected_v) + 2):
                    for point in ((0, 0), (2, 2), (4, 4)):
                        self.assertEqual((time, point) in vertices, (time, point) in expected_v)
                        for next_point in (point, (point[0] + 1, point[1])):
                            edge = (time, point, next_point)
                            self.assertEqual(edge in edges, edge in expected_e)
                for edge in expected_e:
                    self.assertIn(edge, edges)


class AtomicCommandTests(unittest.TestCase):
    def test_rejected_reposition_and_hold_preserve_snapshot_and_reservations(self):
        world = Environment(stream_scene(), router_kind="sipp", positioning=True)
        world.plan_reservations()
        for action in (
            lambda: world.reposition(0, world._scenario.stations[0]),
            lambda: world.hold(0),
        ):
            before = execution_footprint(world)
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(execution_footprint(world), before)
        target = min(world._scenario.transit_only)
        before = execution_footprint(world)
        with patch.object(world._router, "leg", return_value=None):
            with self.assertRaisesRegex(ValueError, "safe positioning"):
                world.reposition(0, target)
        self.assertEqual(execution_footprint(world), before)
        world.assign([(0, 0)])
        before = execution_footprint(world)
        for action in (lambda: world.hold(0), lambda: world.reposition(0, target)):
            with self.assertRaisesRegex(ValueError, "committed"):
                action()
            self.assertEqual(execution_footprint(world), before)

    def test_conflicting_hold_rejects_without_partial_time_or_index_shift(self):
        scene = generate(seed=10, task_count=1, vehicles=2)
        world = Environment(scene, router_kind="sipp")
        world.assign([(0, 0)])
        world.tick(world.tasks.records[0]["delivery_end"] + 1, observe=False)
        point = world.observe()["vehicles"][0]["position"]
        self.assertTrue(world.ruleset.may_wait_at(point))
        vertices, edges = world.plan_reservations().view_excluding(1, world.time)
        approach = world._router.leg(world._plans[1][0], point, world.time, 1, vertices, edges)
        self.assertIsNotNone(approach)
        depart = world._router.leg(
            point, scene.homes[1], world.time + len(approach) - 1, 1, vertices, edges
        )
        self.assertIsNotNone(depart)
        world._replace_plan(1, approach + depart[1:])
        before = execution_footprint(world)
        with self.assertRaisesRegex(ValueError, "conflicts|edge swap"):
            world.hold(0, len(approach))
        self.assertEqual(execution_footprint(world), before)


if __name__ == "__main__":
    unittest.main()
