"""Opt-in positioning controls keep bounded, released-only policy history."""

import unittest
from collections import Counter, deque
from copy import deepcopy
from math import isfinite
from unittest.mock import patch

from agv.policy.positioning import PositioningPolicy
from agv.simulation import Environment
from tests.unit.test_positioning import scene


class PositioningOptionsTests(unittest.TestCase):
    def observation(self):
        return Environment(scene(vehicles=2, release=0), positioning=True).observe()

    def test_stat_window_expires_history_even_when_an_old_job_is_still_pending(self):
        obs = self.observation()
        policy = PositioningPolicy(obs, stat_window=50, rebalance_period=250)
        policy.observe(obs)
        self.assertEqual(set(policy.history), {0})
        self.assertEqual(policy.interval, 250)
        obs["time"] = 50
        policy.observe(obs)
        self.assertEqual(set(policy.history), {0})
        obs["time"] = 51
        policy.observe(obs)
        self.assertEqual(policy.history, {})
        policy.observe(obs)
        self.assertEqual(policy.history, {})

    def test_future_releases_are_never_added_to_window_history(self):
        obs = self.observation()
        policy = PositioningPolicy(obs, stat_window=50)
        obs["pending"][0]["release"] = 100
        policy.observe(obs)
        self.assertEqual(policy.history, {})

    def test_hidden_future_does_not_change_opt_in_decisions(self):
        envs = [
            Environment(scene(vehicles=2, release=0, extra=e), positioning=True) for e in (0, 1)
        ]
        policies = []
        for env in envs:
            env.assign([(0, 0)])
            policies.append(
                PositioningPolicy(
                    env.observe(),
                    stat_window=100,
                    rebalance_period=500,
                    hotspot_zones=1,
                    protect_utilization=0.8,
                )
            )
        self.assertEqual(envs[0].observe(), envs[1].observe())
        self.assertEqual(
            policies[0].action(envs[0].observe()), policies[1].action(envs[1].observe())
        )

    def test_effective_period_does_not_prevent_a_newly_idle_vehicle_decision(self):
        obs = self.observation()
        obs["pending"] = []
        policy = PositioningPolicy(obs, rebalance_period=500)
        point = policy.candidates[0]
        policy.history = {0: (0, (point,))}
        policy.last = 0
        obs["time"] = 20
        with patch("agv.policy.positioning.minimum_assignment", return_value=[]) as choose:
            self.assertEqual(policy.action(obs), [])
            choose.assert_not_called()
            policy.new_idle.add(0)
            policy.action(obs)
            choose.assert_called_once()

    def test_hotspot_adds_one_safe_slot_without_changing_base_capacity(self):
        obs = self.observation()
        obs["pending"] = []
        base = PositioningPolicy(obs, capacity=1)
        hot = PositioningPolicy(obs, capacity=1, hotspot_zones=1)
        zone = next(z for z, points in base.zones.items() if len(points) >= 2)
        point = base.zones[zone][0]
        widths = []
        for policy in (base, hot):
            policy.history = {0: (0, (point,))}
            with patch("agv.policy.positioning.minimum_assignment", return_value=[]) as choose:
                policy.action(obs)
                widths.append(len(choose.call_args.args[0][0]))
            self.assertEqual(policy.capacity, 1)
            self.assertTrue(
                all(p in policy.candidate_set for ps in policy.zones.values() for p in ps)
            )
        self.assertEqual(widths[1], widths[0] + 1)

    def test_utilization_is_time_weighted_capacity_normalized_and_same_tick_idempotent(self):
        obs = self.observation()
        obs["pending"] = []
        policy = PositioningPolicy(obs, stat_window=10, protect_utilization=0.8)
        point = policy.candidates[0]
        zone = policy._zone(point)
        policy.occupancy = deque([(0, Counter({zone: 2})), (5, Counter())])
        self.assertEqual(policy._utilization(zone, 10, 2), 0.5)
        obs["time"] = 20
        policy.observe(obs)
        policy.observe(obs)
        self.assertEqual([t for t, _ in policy.occupancy], [5, 20])
        self.assertEqual(policy._utilization(zone, 20, 2), 0)

    def test_occupancy_protection_applies_only_to_safe_parked_targets(self):
        initial = self.observation()
        initial["pending"] = []
        for parked in (True, False):
            obs = deepcopy(initial)
            policy = PositioningPolicy(obs, capacity=1, protect_utilization=0.8)
            point = policy.candidates[0]
            zone = policy._zone(point)
            policy.history = {0: (0, (point,))}
            policy.occupancy = deque([(0, Counter({zone: 1}))])
            obs["time"] = 10
            obs["positioning_targets"][0] = {"target": point}
            if parked:
                obs["vehicles"][0]["position"] = point
            with patch("agv.policy.positioning.minimum_assignment", return_value=[]) as choose:
                policy.action(obs)
                finite = sum(isfinite(x) for x in choose.call_args.args[0][0])
            if parked:
                self.assertEqual(finite, 1)
            else:
                self.assertGreater(finite, 1)

    def test_invalid_opt_in_values_fail_before_planning(self):
        obs = self.observation()
        for options in (
            {"stat_window": 0},
            {"stat_window": True},
            {"rebalance_period": -1},
            {"hotspot_zones": -1},
            {"hotspot_zones": True},
            {"protect_utilization": 0},
            {"protect_utilization": float("nan")},
            {"capacity": 0},
            {"sigma": 0},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                PositioningPolicy(obs, **options)


if __name__ == "__main__":
    unittest.main()
