"""Exact cache keys and real planner calls, including cross-tick busy-car reuse."""

import unittest
from copy import deepcopy
from dataclasses import replace

from agv.planning import create_router
from agv.planning.cache import EtaCache
from agv.planning.distance import DistanceOracle, _distances
from agv.policy.stream import ArrivalMatching
from agv.runner.environment import Environment
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


class EtaCacheTests(unittest.TestCase):
    def test_exact_hit_changed_reservation_and_failure(self):
        cache = EtaCache()
        calls = []

        def compute():
            calls.append(1)
            return float("inf")

        self.assertEqual(cache.get_or_compute("query", (1,), compute), float("inf"))
        self.assertEqual(cache.get_or_compute("query", (1,), compute), float("inf"))
        self.assertEqual(cache.get_or_compute("query", (2,), compute), float("inf"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(cache.snapshot()["hits"], 1)
        self.assertEqual(cache.snapshot()["invalidations"], 1)

    def test_lru_evicts_least_recent_entry(self):
        cache = EtaCache(capacity=2)
        for query in ("a", "b", "a", "c", "a", "b"):
            cache.get_or_compute(query, (), lambda: 1)
        self.assertEqual(cache.snapshot()["hits"], 2)
        self.assertEqual(cache.snapshot()["evictions"], 2)
        self.assertEqual(cache.snapshot()["entries"], 2)
        for capacity in (False, 0, -1, 1.5):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                EtaCache(capacity)

    def test_exception_does_not_store_a_successful_result(self):
        cache = EtaCache()
        with self.assertRaisesRegex(ValueError, "failed"):
            cache.get_or_compute("q", (), lambda: (_ for _ in ()).throw(ValueError("failed")))
        self.assertEqual(cache.snapshot()["entries"], 0)
        self.assertEqual(cache.get_or_compute("q", (), lambda: 2), 2)


class DistanceSharingTests(unittest.TestCase):
    def scene(self):
        return Scenario(5, 3, set(), set(), [(0, 0), (4, 0)], [], stations=[(2, 1)])

    def test_tables_are_shared_read_only_and_home_permissions_are_distinct(self):
        scene = self.scene()
        first, second = DistanceOracle(scene), DistanceOracle(deepcopy(scene))
        table = first.distances((3, 2), 0)
        self.assertIs(table, second.distances((3, 2), 0))
        with self.assertRaises(TypeError):
            table[(0, 0)] = 999
        self.assertNotIn((4, 0), table)
        self.assertIn((4, 0), second.distances((3, 2), 1))

    def test_geometry_horizon_and_terminal_access_are_isolated(self):
        scene = self.scene()
        ordinary = DistanceOracle(scene).distances((3, 1), 0)
        strict = DistanceOracle(replace(scene, map_info={"station_access": "delivery_only"}))
        self.assertEqual(ordinary[(1, 1)], 2)
        self.assertEqual(strict.distance((1, 1), (3, 1), 0), 4)
        self.assertEqual(strict.distance((1, 1), (2, 1), 0), 1)
        self.assertIsNot(ordinary, DistanceOracle(replace(scene, horizon=30)).distances((3, 1), 0))
        changed = DistanceOracle(replace(scene, blocked={(2, 1)}))
        self.assertEqual(changed.distance((1, 1), (3, 1), 0), 4)

    def test_shared_tables_and_instance_references_are_bounded(self):
        oracle = DistanceOracle(Scenario(150, 1, set(), set(), [(0, 0)], []))
        for x in range(140):
            oracle.distances((x, 0), 0)
        self.assertEqual(len(oracle.cache), 64)
        self.assertLessEqual(_distances.cache_info().currsize, 128)

    def test_deepcopy_detaches_router_containers_and_keeps_subclass_fields(self):
        for kind in ("astar", "sipp"):
            with self.subTest(kind=kind):
                router = create_router(kind, self.scene())
                table = router.distances((3, 2), 0)
                router.extra_state = {"values": [1]}
                router.stats["calls"] = 3
                clone = deepcopy(router)
                self.assertIs(type(clone), type(router))
                self.assertIsNot(clone, router)
                self.assertIsNot(clone.s, router.s)
                self.assertIsNot(clone.cache, router.cache)
                self.assertIs(clone.distances((3, 2), 0), table)
                clone.stats["calls"] += 1
                clone.extra_state["values"].append(2)
                clone.cache.clear()
                self.assertEqual(router.stats["calls"], 3)
                self.assertEqual(router.extra_state, {"values": [1]})
                self.assertEqual(len(router.cache), 1)

    def test_snapshot_and_deepcopy_environment_keep_counters_independent(self):
        env = Environment(generate_current(task_count=2, vehicles=2, seed=10), router_kind="sipp")
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        table = next(iter(env._router.cache.values()))
        state = deepcopy(env.__dict__)
        clone = env.snapshot()
        for router in (state["_router"], clone._router):
            self.assertIsNot(router, env._router)
            self.assertIsNot(router.stats, env._router.stats)
            self.assertIsNot(router.cache, env._router.cache)
            self.assertIn(table, router.cache.values())
            self.assertTrue(any(value is table for value in router.cache.values()))
            calls = env._router.stats["calls"]
            router.stats["calls"] += 1
            self.assertEqual(env._router.stats["calls"], calls)
        clone.tick(1, observe=False)
        self.assertEqual(env.time, 0)


class ArrivalCacheTests(unittest.TestCase):
    def observation(self):
        return Environment(generate_current(task_count=2, vehicles=2, seed=10)).observe()

    def test_duplicate_observation_reuses_real_calls_and_new_time_does_not(self):
        observation = self.observation()
        matcher = ArrivalMatching(observation, eta_cache=EtaCache())
        expected = matcher.action(observation)
        calls = matcher.router.stats["calls"]
        self.assertEqual(matcher.action(deepcopy(observation)), expected)
        self.assertEqual(matcher.router.stats["calls"], calls)
        changed = deepcopy(observation)
        changed["time"] += 1
        matcher.action(changed)
        self.assertGreater(matcher.router.stats["calls"], calls)

    def test_changed_peer_reservations_invalidate_only_affected_vehicle(self):
        observation = self.observation()
        matcher = ArrivalMatching(observation, eta_cache=EtaCache())
        matcher.action(observation)
        changed = deepcopy(observation)
        peer = changed["vehicles"][1]
        peer["return_path"] = peer["return_path"] + [peer["position"]]
        matcher.action(changed)
        self.assertGreater(matcher.eta_cache.snapshot()["invalidations"], 0)
        self.assertGreater(matcher.eta_cache.snapshot()["hits"], 0)

    def test_task_service_geometry_and_horizon_cannot_share_wrong_eta(self):
        observation = self.observation()
        cache = EtaCache()
        ArrivalMatching(observation, eta_cache=cache).action(observation)
        variants = []
        for field, value in (("horizon", 1),):
            changed = deepcopy(observation)
            changed[field] = value
            variants.append(changed)
        changed = deepcopy(observation)
        changed["pending"][0]["pickup_service"] += 2
        variants.append(changed)
        variants.append(
            Environment(generate_current(size="large", task_count=2, vehicles=2, seed=10)).observe()
        )
        for changed in variants:
            with self.subTest(horizon=changed["horizon"]):
                cached = ArrivalMatching(changed, eta_cache=cache)
                plain = ArrivalMatching(changed)
                self.assertEqual(cached.action(changed), plain.action(changed))
                self.assertEqual(cached.log, plain.log)
                self.assertGreater(cached.router.stats["calls"], 0)

    def test_busy_vehicle_uses_same_exact_departure_across_ticks(self):
        env = Environment(generate_current(task_count=3, vehicles=2, seed=10))
        self.assertTrue(env.assign([(0, 0)])[0]["accepted"])
        first = env.observe()
        env.advance(1)
        second = env.observe()
        cached = ArrivalMatching(first, delay=True, max_wait=1000, eta_cache=EtaCache())
        plain = ArrivalMatching(first, delay=True, max_wait=1000)
        for observation in (first, second):
            self.assertEqual(cached.action(observation), plain.action(observation))
        self.assertEqual(cached.log, plain.log)
        self.assertGreater(cached.eta_cache.snapshot()["hits"], 0)
        self.assertLess(cached.router.stats["calls"], plain.router.stats["calls"])

    def test_unreleased_orders_do_not_enter_cache_or_change_a_decision(self):
        scene = generate_current(task_count=2, vehicles=2, seed=10)
        scene.tasks[1] = replace(scene.tasks[1], release=500)
        scene.order_stream_end = 600
        other = deepcopy(scene)
        other.tasks[1] = replace(other.tasks[1], delivery=other.stations[-1], release=550)
        first = Environment(scene.check()).observe()
        second = Environment(other.check()).observe()
        self.assertEqual(first, second)
        matcher = ArrivalMatching(first, eta_cache=EtaCache())
        expected = matcher.action(first)
        calls = matcher.router.stats["calls"]
        self.assertEqual(matcher.action(second), expected)
        self.assertEqual(matcher.router.stats["calls"], calls)
        self.assertGreater(matcher.eta_cache.snapshot()["hits"], 0)


if __name__ == "__main__":
    unittest.main()
