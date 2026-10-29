"""Mixed-flow physics and input boundaries independent of search strategies."""

import ast
import gzip
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agv.data.wepa import build, read_source
from agv.evaluation.wepa import validate
from agv.planning.sipp import SafeIntervalRouter
from agv.warehouse.scenarios import Scenario
from agv.world.itinerary import Itinerary
from agv.world.transit import advance_fleet
from agv.world.wepa import World
from agv.world.wepa_snapshot import ShadowWorld, observation, snapshot


def micro_model(kinds=("retrieval", "delivery")):
    free = {(x, y) for x in range(1, 8) for y in (2, 4)}
    free |= {(4, y) for y in range(7)} | {(x, 3) for x in (1, 7)} | {(0, 2), (0, 4)}
    homes, stations = [(0, 2), (0, 4)], [(4, 0), (4, 6)]
    specs = [((2, 1), (2, 2), 10), ((6, 5), (6, 4), 20)]
    pickup = {point for _, point, _ in specs}
    catalogue, slots = [], []
    for bay, (shelf, point, sku) in enumerate(specs):
        catalogue.append(
            dict(position=shelf, loading_points=[point], levels=3, bay_id=bay, pair_id=bay, bay=1)
        )
        for level in range(1, 4):
            slots.append(
                dict(id=len(slots), sku=sku, bay=bay, shelf=shelf, level=level, points=[point])
            )
    scene = Scenario(
        width=9,
        height=7,
        blocked={(x, y) for x in range(9) for y in range(7)} - free,
        shelves={shelf for shelf, _, _ in specs},
        homes=homes,
        tasks=[],
        horizon=None,
        pickup_zones=pickup,
        stations=stations,
        transit_only=free - pickup - set(stations) - set(homes),
        map_info=dict(
            rack_catalog=catalogue,
            station_access="delivery_only",
            model_version="micro-joint-reference-v1",
        ),
    )
    tasks = [
        dict(
            id=i,
            kind=kind,
            sku=10 if kind == "retrieval" else 20,
            release=0,
            port=stations[0 if kind == "delivery" else 1],
        )
        for i, kind in enumerate(kinds)
    ]
    return dict(
        case="micro-wepa-physics",
        scene=scene,
        slots=slots,
        occupied={0, 1, 2},
        tasks=tasks,
        vehicles=2,
        close_at=0,
        size="micro",
        layers=3,
    )


def execute(model):
    world = World(model, router=SafeIntervalRouter(model["scene"]))
    while world.time < 300:
        world.publish_and_complete()
        if world.done:
            break
        for vehicle, active in enumerate(world.active):
            if active is not None:
                continue
            for job in world.ready():
                proposal = world.trip(vehicle, job)
                if proposal is not None:
                    world.commit(vehicle, job, proposal)
                    world.decisions.append(
                        dict(
                            time=world.time,
                            pairs=[(vehicle, job["id"])],
                            visible_ids=sorted(world.visible),
                        )
                    )
                    break
        world.advance()
    jobs, records = world.tasks, world.records
    flows = [r["end"] - jobs[r["task"]]["release"] for r in records]
    moves = sum(a != b for p in world.history for a, b in zip(p, p[1:]))
    empty = sum(
        a != b and label != "loaded"
        for p, labels in zip(world.history, world.labels)
        for a, b, label in zip(p, p[1:], labels)
    )
    result = dict(
        valid=world.done,
        paths=world.history,
        labels=world.labels,
        time=world.time,
        records=records,
        completed=sorted(world.completed),
        decisions=world.decisions,
        T=max(r["end"] for r in records),
        R=sum(flows) / len(flows),
        D=moves,
        empty_distance=empty,
        final_stock=sorted(world.stock),
    )
    return world, result


class WepaKernelTests(unittest.TestCase):
    def test_shared_transit_records_states_and_advances_immutable_route(self):
        plans = [Itinerary([(0, 0), (1, 0), (2, 0)]), [(0, 2)]]
        histories = [[plan[0]] for plan in plans]
        labels = [[], []]
        time, moves = advance_fleet(plans, histories, labels, lambda k: ("empty", "idle")[k], 4)
        self.assertEqual((time, moves), (5, 1))
        self.assertEqual(histories, [[(0, 0), (1, 0)], [(0, 2), (0, 2)]])
        self.assertEqual(labels, [["empty"], ["idle"]])
        self.assertIsInstance(plans[0], Itinerary)
        storage = plans[0].cells
        time, moves = advance_fleet(plans, histories, labels, lambda k: "empty", time)
        self.assertEqual((time, moves), (6, 1))
        self.assertIs(plans[0].cells, storage)
        self.assertEqual(plans[0][0], (2, 0))
        legacy = [[(0, 0), (1, 0)]]
        advance_fleet(legacy, [[(0, 0)]], [[]], lambda k: "empty", 0)
        self.assertIs(type(legacy[0]), list)

    def test_observation_hides_future_and_refreshes_after_checked_command(self):
        model = micro_model()
        model["tasks"][1]["release"] = 100
        model["close_at"] = 900
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        public = observation(world)
        self.assertEqual(set(public.tasks), {0})
        self.assertEqual(public.model["close_at"], 0)
        self.assertEqual(public.scene.tasks, [])
        self.assertIsNone(public.scene.order_stream_end)
        self.assertFalse(hasattr(public, "done"))
        self.assertFalse(hasattr(public, "history"))
        with self.assertRaises(TypeError):
            public.visible[0]["release"] = 10
        with self.assertRaises(TypeError):
            public.plans[0].append((1, 2))
        job = public.ready()[0]
        public.commit(0, job, public.trip(0, job))
        self.assertIn(0, public.assigned)
        self.assertIsNotNone(public.active[0])
        self.assertEqual(world.assigned, {0})

    def test_snapshot_is_detached_and_contains_only_released_tasks(self):
        model = micro_model()
        model["tasks"][1]["release"] = 100
        model["close_at"] = 900
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        view = snapshot(observation(world), router_factory=SafeIntervalRouter)
        self.assertIsInstance(view, ShadowWorld)
        self.assertEqual(set(view.tasks), {0})
        self.assertEqual(view.model["close_at"], world.time)
        view.stock.clear()
        view.visible[0]["release"] = 10
        view.router.stats["calls"] += 1
        self.assertEqual(world.stock, {0, 1, 2})
        self.assertEqual(world.visible[0]["release"], 0)
        self.assertNotEqual(view.router.stats, world.router.stats)

    def test_quiet_forecast_jump_matches_repeated_physical_ticks(self):
        model = micro_model(("retrieval",))
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        job = world.ready()[0]
        world.commit(0, job, world.trip(0, job))
        view = snapshot(world, router_factory=SafeIntervalRouter)
        self.assertTrue(view.jump_quiet())
        while world.time < view.time:
            world.advance()
        world.publish_and_complete()
        view.publish_and_complete()
        for field in ("time", "plans", "past_moves", "stock", "completed", "active"):
            self.assertEqual(getattr(world, field), getattr(view, field), field)
        self.assertEqual(world.ready(), view.ready())

    def test_noninteger_route_cannot_be_committed(self):
        model = micro_model()
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        job = world.ready()[0]
        path, record = world.trip(0, job)
        path[1] = (float(path[1][0]), path[1][1])
        with self.assertRaisesRegex(ValueError, "integer cells"):
            world.commit(0, job, (path, record))
        self.assertFalse(world.assigned)

    def test_trip_can_depart_previous_terminal_at_unload_completion(self):
        model = micro_model(("retrieval", "retrieval"))
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        job = world.ready()[0]
        proposal = world.trip(0, job)
        world.commit(0, job, proposal)
        while world.time < proposal[1]["end"]:
            world.advance()
            world.publish_and_complete()
        self.assertIn(world.plans[0][0], world.scene.stations)
        job = world.ready()[0]
        following = world.trip(0, job)
        world.commit(0, job, following)
        self.assertEqual(world.assigned, {0, 1})
        self.assertNotEqual(following[0][0], following[0][1])

    def test_stock_changes_only_at_physical_completion(self):
        model = micro_model()
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        self.assertEqual(world.stock, {0, 1, 2})
        self.assertEqual(world.bound, {0: 2, 1: 3})
        outbound = world.ready()[0]
        proposal = world.trip(0, outbound)
        world.commit(0, outbound, proposal)
        self.assertEqual(world.stock, {0, 1, 2})
        world.time = proposal[1]["pickup_end"]
        world.publish_and_complete()
        self.assertEqual(world.stock, {0, 1})
        self.assertNotIn(2, world.out_reserved)

    def test_shelf_order_and_bay_lock_prevent_parallel_lower_pickup(self):
        model = micro_model(("retrieval", "retrieval"))
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        self.assertEqual(world.bound, {0: 2, 1: 1})
        self.assertEqual([job["id"] for job in world.ready()], [0])
        proposal = world.trip(0, world.ready()[0])
        world.commit(0, world.ready()[0], proposal)
        self.assertFalse(world.ready())
        world.time = proposal[1]["pickup_end"]
        world.publish_and_complete()
        self.assertEqual([job["id"] for job in world.ready()], [1])

    def test_malformed_proposal_is_rejected_without_partial_mutation(self):
        model = micro_model()
        world = World(model, router=SafeIntervalRouter(model["scene"]))
        world.publish_and_complete()
        job = world.ready()[0]
        proposal = world.trip(0, job)
        proposal[1]["pickup_end"] += 1
        before = deepcopy(
            (
                world.plans,
                world.records,
                world.active,
                world.assigned,
                world.locks,
                world.stock,
                world.out_reserved,
                world.in_reserved,
            )
        )
        with self.assertRaises(ValueError):
            world.commit(0, job, proposal)
        after = (
            world.plans,
            world.records,
            world.active,
            world.assigned,
            world.locks,
            world.stock,
            world.out_reserved,
            world.in_reserved,
        )
        self.assertEqual(before, after)

    def test_mixed_run_passes_independent_audit_and_detects_tampering(self):
        model = micro_model()
        world, result = execute(model)
        self.assertTrue(validate(model, result)["valid"])
        self.assertEqual(world.stock, {0, 1, 3})
        forged = deepcopy(result)
        forged["final_stock"] = [0, 1]
        with self.assertRaisesRegex(ValueError, "Final inventory mismatch"):
            validate(model, forged)
        forged = deepcopy(result)
        forged["decisions"][0]["visible_ids"].append(100)
        with self.assertRaisesRegex(ValueError, "future jobs"):
            validate(model, forged)
        forged = deepcopy(result)
        forged["records"][0]["vehicle"] = -1
        with self.assertRaisesRegex(ValueError, "Unknown vehicle"):
            validate(model, forged)

    def test_checker_does_not_import_runtime(self):
        import agv.evaluation.wepa as checker

        tree = ast.parse(Path(checker.__file__).read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(
            any(name.startswith(("agv.world", "agv.policy", "agv.runner")) for name in imports)
        )

    def test_data_mapping_is_deterministic_and_does_not_mutate_case(self):
        case = dict(
            case="test",
            initial={"10": 3},
            close_at=900,
            tasks=[dict(id=0, kind="retrieval", sku=10, release=0, source_dock=1)],
        )
        original = deepcopy(case)
        first, second = build(case), build(case)
        self.assertEqual(first["slots"], second["slots"])
        self.assertEqual(first["occupied"], second["occupied"])
        self.assertEqual(first["tasks"], second["tasks"])
        self.assertEqual(case, original)

    def test_raw_directory_supports_gzip_and_pinned_uncompressed_hash(self):
        orders = json.dumps([["delivery", 10, 0, 1, 2, 3]]).encode()
        inventory = b'{"10": 3}'
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp)
            (raw / "2_orders.json.gz").write_bytes(gzip.compress(orders))
            (raw / "3_initial_fill_lvl.json").write_bytes(inventory)
            rows, stock, hashes = read_source(
                raw, expected_hashes={"2_orders.json": hashlib.sha256(orders).hexdigest()}
            )
            self.assertEqual(rows[0][1], 10)
            self.assertEqual(stock[10], 3)
            self.assertEqual(
                hashes["3_initial_fill_lvl.json"], hashlib.sha256(inventory).hexdigest()
            )
            with self.assertRaisesRegex(ValueError, "Pinned source hash mismatch"):
                read_source(raw, expected_hashes={"2_orders.json": "wrong"})


if __name__ == "__main__":
    unittest.main()
