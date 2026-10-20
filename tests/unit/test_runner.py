"""Composition, command ordering and historical registry compatibility."""

import importlib
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import patch

from agv.core import Profile
from agv.policy.controller import BaselineReporter, CallableAssignment, Controller
from agv.registry import (
    DISPATCH_SOLVERS,
    SOLVERS,
    STREAM_SOLVERS,
    AssignSpec,
    IdleSpec,
    RepairSpec,
    SolverSpec,
    run_raw,
)

runner = importlib.import_module("agv.runner.run")


class RunnerTests(unittest.TestCase):
    def test_composed_stages_use_committed_observations_in_order(self):
        events = []

        class World:
            def __init__(self, scenario, **options):
                self.time = self.version = 0

            @property
            def done(self):
                return self.time == 1

            def observe(self):
                events.append(("observe", self.version))
                return dict(version=self.version)

            def assign(self, action):
                events.append(("assign", action))
                self.version += 1
                return [dict(accepted=True)]

            def reposition(self, vehicle, target):
                events.append(("position", vehicle, target))
                self.version += 1

            def apply_replan(self, proposal):
                events.append(("repair", proposal))

            def stop_if_stalled(self, feedback):
                events.append(("stall",))
                return False

            def prepare_idle(self):
                events.append(("hold",))

            def tick(self, steps, *, observe):
                events.append(("tick", steps, observe))
                self.time += steps

            def result(self):
                return dict(done=True)

        class Idle:
            def observe(self, observation, context):
                events.append(("idle_history", observation["version"]))

            def due(self, observation):
                events.append(("idle_due", observation["version"]))
                return True

            def decide(self, observation, context):
                events.append(("idle_decide", observation["version"]))
                return [(0, (1, 2))]

        class Repair:
            def due(self, time, feedback):
                return True

            def decide(self, observation, context):
                events.append(("repair_decide", observation["version"]))
                return dict(version=observation["version"])

        def action(observation):
            events.append(("dispatch", observation["version"]))
            return [(0, 3)]

        controller = Controller(CallableAssignment(action), BaselineReporter(), Idle(), Repair())
        with (
            patch.object(runner, "Environment", World),
            patch("agv.registry.build_controller", return_value=controller),
        ):
            self.assertEqual(
                runner.run(
                    SolverSpec(),
                    SimpleNamespace(horizon=1, is_v9_1=False, is_v9=False, is_v4=False),
                ),
                dict(done=True),
            )
        self.assertEqual(
            events,
            [
                ("observe", 0),
                ("idle_history", 0),
                ("dispatch", 0),
                ("assign", [(0, 3)]),
                ("idle_due", 0),
                ("observe", 1),
                ("idle_decide", 1),
                ("position", 0, (1, 2)),
                ("observe", 2),
                ("repair_decide", 2),
                ("repair", dict(version=2)),
                ("stall",),
                ("hold",),
                ("tick", 1, False),
            ],
        )

    def test_profile_declarations_preserve_all_historical_name_boundaries(self):
        stream = {"sipp_stream_dispatch", *STREAM_SOLVERS}
        standby = {f"sipp_standby{n}_dispatch" for n in (8, 16, 32)}
        expected = {
            Profile.LEGACY: set(SOLVERS) - stream - standby,
            Profile.V4: set(SOLVERS) - stream - standby,
            Profile.V9: set(SOLVERS) - stream,
            Profile.V91: stream | {"baseline"},
        }
        with patch("agv.runner.run", return_value={}) as execute:
            for profile in Profile:
                scenario = SimpleNamespace(
                    is_v9_1=profile == Profile.V91,
                    is_v9=profile in (Profile.V9, Profile.V91),
                    is_v4=profile == Profile.V4,
                )
                for name in SOLVERS:
                    with self.subTest(profile=profile, name=name):
                        execute.reset_mock()
                        if name in expected[profile]:
                            run_raw(name, scenario)
                            execute.assert_called_once_with(SOLVERS[name], scenario)
                        else:
                            with self.assertRaises(ValueError):
                                run_raw(name, scenario)
                            execute.assert_not_called()
        self.assertEqual(len(SOLVERS), 23)
        self.assertEqual(len(DISPATCH_SOLVERS), 8)
        self.assertEqual(len(STREAM_SOLVERS), 6)

    def test_specs_are_immutable_and_assignment_is_never_an_alias_name(self):
        for spec in SOLVERS.values():
            self.assertIsInstance(spec, SolverSpec)
            self.assertIsInstance(spec.profiles, frozenset)
            self.assertIn(spec.assign.kind, ("greedy", "matching", "eta_matching", "bcrd"))
        with self.assertRaises(FrozenInstanceError):
            SOLVERS["baseline"].router = "sipp"
        with self.assertRaisesRegex(ValueError, "Unknown algorithm"):
            run_raw("missing", SimpleNamespace())

    def test_environment_compatibility_import_preserves_class_and_patch_identity(self):
        from agv.runner.environment import Environment
        from agv.simulation import Environment as CompatibilityEnvironment

        self.assertIs(CompatibilityEnvironment, Environment)

    def test_baseline_adapter_keeps_explicit_invalid_policy_as_a_recorded_failure(self):
        from agv.evaluation.validation import validate
        from agv.runner.compat import run_baseline
        from agv.warehouse.scenarios import example

        scenario = example(task_count=1)
        result = run_baseline(scenario, policy=None)
        self.assertEqual(result["reason"], "policy_error")
        self.assertEqual(result["diagnostics"]["execution_error"]["type"], "TypeError")
        self.assertTrue(validate(scenario, result))

    def test_runner_itself_checks_profile_before_constructing_a_world(self):
        from agv.warehouse.mixed import generate_current
        from agv.warehouse.scenarios import example

        cases = (
            ("sipp_matching_dispatch", generate_current(task_count=0, vehicles=1)),
            ("sipp_stream_matching", example(task_count=0)),
        )
        with patch.object(runner, "Environment") as factory:
            for name, scenario in cases:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    runner.run(SOLVERS[name], scenario)
            factory.assert_not_called()

    def test_inconsistent_specs_cannot_silently_execute_a_different_stage(self):
        for kind, style in (
            ("matching", "baseline"),
            ("eta_matching", "optimized"),
            ("eta_matching", "dispatch"),
            ("matching", "stream"),
            ("bcrd", "stream"),
        ):
            with (
                self.subTest(kind=kind, style=style),
                self.assertRaisesRegex(ValueError, "incompatible with result_style"),
            ):
                SolverSpec(router="sipp", assign=AssignSpec(kind=kind), result_style=style)
        # Supported stages remain composable; these options are all honored by
        # the existing optimizer and profile-driven idle stage.
        SolverSpec(
            router="sipp",
            assign=AssignSpec(kind="matching"),
            idle=IdleSpec(kind="standby", hold_steps=8),
            repair=RepairSpec(),
            profiles=frozenset((Profile.V9,)),
            result_style="optimized",
        )

    def test_reset_on_another_map_rebuilds_idle_geometry_and_matches_fresh_world(self):
        from agv.policy.bcrd import fallback
        from agv.runner.environment import Environment
        from agv.warehouse.mixed import generate_current

        reused = Environment(
            generate_current(size="medium", vehicles=1, task_count=0, order_stream_end=400)
        )
        reused.prepare_idle()
        scenario = generate_current(
            size="large", vehicles=1, task_count=1, seed=10, order_stream_end=400
        )
        reused.reset(scenario)
        fresh = Environment(scenario)
        for _ in range(100):
            for world in (fresh, reused):
                world.assign(fallback(world.observe_view()))
                world.advance(observe=False)
        expected, actual = fresh.result(), reused.result()
        self.assertGreater(expected["standby_steps"], 0)
        self.assertEqual(actual["paths"], expected["paths"])
        self.assertEqual(actual["idle_waits"], expected["idle_waits"])

    def test_unvalidated_bcrd_positioning_combination_stays_rejected(self):
        with self.assertRaisesRegex(ValueError, "separately validated"):
            SolverSpec(assign=AssignSpec(kind="bcrd"), idle=IdleSpec(kind="positioning"))


if __name__ == "__main__":
    unittest.main()
