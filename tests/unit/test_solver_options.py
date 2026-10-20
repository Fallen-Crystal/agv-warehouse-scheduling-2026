"""Optional mechanisms cross the composition root without changing old defaults."""

import unittest
from dataclasses import replace

from agv.evaluation.validation import validate
from agv.registry import SOLVERS, AssignSpec, IdleSpec, SolverSpec, build_controller
from agv.runner import run
from agv.runner.environment import Environment
from agv.warehouse.mixed import generate_current


class SolverOptionsTests(unittest.TestCase):
    def test_invalid_options_fail_at_construction(self):
        for options in (
            dict(kind="typo"),
            dict(event_driven=1),
            dict(max_batches=True),
            dict(depth=-1),
            dict(mode="typo"),
            dict(min_queue_ratio=float("nan")),
            dict(eta_cache_capacity=True),
            dict(eta_cache_capacity=10),
            dict(route_budget=10),
            dict(kind="bcrd", expansion_budget=-1),
            dict(kind="bcrd", step_budget=1.5),
            dict(kind="eta_matching", tail_guard=True),
            dict(kind="eta_matching", max_batches=1),
            dict(kind="matching", depth=0),
            dict(kind="greedy", mode="order"),
            dict(kind="eta_matching", min_queue_ratio=0),
            dict(kind="eta_matching", event_driven=False),
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                AssignSpec(**options)
        for options in (
            dict(kind="typo"),
            dict(hold_steps=True),
            dict(hold_steps=8),
            dict(stat_window=50),
            dict(kind="positioning", stat_window=0),
            dict(kind="positioning", rebalance_period=False),
            dict(kind="positioning", hotspot_zones=-1),
            dict(kind="positioning", protect_utilization=float("nan")),
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                IdleSpec(**options)
        with self.assertRaises(ValueError):
            SolverSpec(router="typo")
        with self.assertRaises(ValueError):
            SolverSpec(profiles=frozenset())

    def test_cache_is_opt_in_and_does_not_change_execution(self):
        scene = generate_current(task_count=4, vehicles=2, mode="static", seed=10)
        spec = SOLVERS["sipp_position_delay_dispatch"]
        old = run(spec, scene)
        cached = run(replace(spec, assign=replace(spec.assign, eta_cache_capacity=64)), scene)
        self.assertNotIn("eta_cache_stats", old)
        self.assertEqual(cached["eta_cache_stats"]["capacity"], 64)
        self.assertGreater(cached["eta_cache_stats"]["requests"], 0)
        for field in ("paths", "assignments", "positioning_events", "makespan", "moves"):
            self.assertEqual(old[field], cached[field], field)
        self.assertTrue(validate(scene, cached))

    def test_positioning_parameters_are_wired_and_reported_only_when_enabled(self):
        scene = generate_current(task_count=0, vehicles=1, order_stream_end=1)
        spec = SOLVERS["sipp_position_dispatch"]
        original = run(spec, scene)
        options = IdleSpec(
            kind="positioning",
            stat_window=100,
            rebalance_period=500,
            hotspot_zones=1,
            protect_utilization=0.8,
        )
        configured = replace(spec, idle=options)
        controller = build_controller(
            configured, Environment(scene).observe_view(), world_factory=Environment
        )
        self.assertEqual(controller.idle.locator.interval, 500)
        result = run(configured, scene)
        parameters = result["algorithm"]["positioning_parameters"]
        for field in ("stat_window", "rebalance_period", "hotspot_zones", "protect_utilization"):
            self.assertNotIn(field, original["algorithm"]["positioning_parameters"])
            self.assertEqual(parameters[field], getattr(options, field))
        self.assertTrue(validate(scene, result))

    def test_runtime_budget_override_is_recorded_as_executed(self):
        scene = generate_current(task_count=8, vehicles=2, mode="static", seed=10)
        spec = SOLVERS["sipp_stream_bcrd"]
        spec = replace(spec, assign=replace(spec.assign, route_budget=120))
        result = run(spec, scene, budget={"max_route_calls": 0})
        self.assertEqual(result["algorithm"]["rollout_budget"], dict(max_route_calls=0))
        self.assertEqual(result["dispatch_stats"]["shadow_route_calls"], 0)
        self.assertTrue(validate(scene, result))

    def test_zero_rollout_budget_keeps_legal_greedy_fallback(self):
        scene = generate_current(task_count=8, vehicles=2, mode="static", seed=10)
        spec = SOLVERS["sipp_stream_bcrd"]
        constrained = replace(spec, assign=replace(spec.assign, route_budget=0))
        result = run(constrained, scene)
        control = run(SOLVERS["sipp_stream_dispatch"], scene)
        self.assertEqual(result["paths"], control["paths"])
        self.assertEqual(result["assignments"], control["assignments"])
        self.assertEqual(result["dispatch_stats"]["shadow_route_calls"], 0)
        self.assertEqual(result["algorithm"]["rollout_budget"], dict(max_route_calls=0))
        self.assertTrue(validate(scene, result))


if __name__ == "__main__":
    unittest.main()
