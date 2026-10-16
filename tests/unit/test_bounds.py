import itertools
import random
import unittest
from math import inf

from agv.dispatch.bcrd import run as run_sipp
from agv.dispatch.greedy import run
from agv.domain import Scenario, Task
from agv.evaluation.bounds import _assignment_cost, lower_bounds
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.warehouse.mixed import generate_current


def singleton(release=0):
    return Scenario(
        5, 3, {(2, 1)}, {(2, 1)}, [(0, 0)], [Task(10, (1, 1), (4, 1), release)], 200
    ).check()


class LowerBoundTests(unittest.TestCase):
    def test_singleton_uses_obstacles_and_final_return(self):
        scene = singleton()
        bounds = lower_bounds(scene)
        self.assertEqual((bounds["T"], bounds["R"], bounds["D"]), (9, 9, 12))
        self.assertEqual(bounds["details"]["D_loaded_only"], 5)
        self.assertEqual(bounds["details"]["D_before_last_delivery"], 7)
        result = run(scene)
        self.assertTrue(validate(scene, result))
        self.assertEqual(result["moves"], bounds["D"])

    def test_release_does_not_add_initial_travel_twice(self):
        bounds = lower_bounds(singleton(50))
        # A hypothetical offline vehicle can reach pickup at t=2 and wait for
        # release=50, then load, travel five obstacle-aware steps, and unload.
        self.assertEqual(bounds["T"], 57)
        self.assertEqual(bounds["R"], 7)
        self.assertLess(bounds["T"], 50 + 2 + 1 + 5 + 1)

    def test_empty_stream_has_zero_task_metrics(self):
        scene = generate_current(task_count=0, vehicles=2, order_stream_end=40)
        bounds = lower_bounds(scene)
        self.assertEqual((bounds["T"], bounds["R"], bounds["D"]), (0, 0, 0))
        # Stream-closing wall-clock time is not the last-delivery metric T.
        self.assertEqual(bounds["details"]["tasks"], [])

    def test_loaded_and_approach_use_the_same_pickup_side(self):
        scene = Scenario(
            5,
            3,
            {(2, 1)},
            {(2, 1)},
            [(0, 1)],
            [Task(0, None, (4, 1), shelf=(2, 1))],
            100,
        ).check()
        bounds = lower_bounds(scene)
        self.assertEqual(bounds["details"]["D_loaded_only"], 1)
        # The left side is one step from H and the right side one from D, but
        # choosing both would invent an impossible two-step combined journey.
        self.assertEqual(bounds["T"], 8)
        self.assertEqual(bounds["D"], 12)

    def test_hungarian_matches_exhaustive_injections_with_forbidden_arcs(self):
        rng = random.Random(17)
        for rows in range(1, 5):
            for columns in (rows, rows + 1):
                for _ in range(6):
                    costs = [
                        [rng.randrange(10) if rng.random() > 0.25 else inf for _ in range(columns)]
                        for _ in range(rows)
                    ]
                    expected = min(
                        sum(costs[i][j] for i, j in enumerate(assignment))
                        for assignment in itertools.permutations(range(columns), rows)
                    )
                    if expected == inf:
                        with self.assertRaises(ValueError):
                            _assignment_cost(costs)
                    else:
                        self.assertEqual(_assignment_cost(costs), expected)

    def test_bounds_below_every_exact_small_static_task_chain(self):
        scene = Scenario(
            7,
            5,
            {(2, 2), (4, 2)},
            {(2, 2), (4, 2)},
            [(0, 0), (0, 4)],
            [
                Task(0, (2, 1), (6, 1), release=0),
                Task(1, (4, 3), (6, 3), release=10),
                Task(2, (2, 3), (5, 4), release=3),
            ],
            200,
        ).check()
        router, bounds = Router(scene), lower_bounds(scene)
        exact = [inf, inf, inf]
        # Enumerate vehicle choices and every per-vehicle task ordering. This
        # exact static relaxation omits conflicts but keeps vehicle identity,
        # release times, task continuity and compulsory own-home final returns.
        for permutation in itertools.permutations(scene.tasks):
            for assignment in itertools.product(range(2), repeat=3):
                completions, moves = [], 0
                for vehicle, home in enumerate(scene.homes):
                    time, position = 0, home
                    for job, choice in zip(permutation, assignment):
                        if choice != vehicle:
                            continue
                        approach = router.distance(position, job.pickup, vehicle)
                        loaded = router.distance(job.pickup, job.delivery, vehicle)
                        time = max(time + approach, job.release)
                        time += job.pickup_service + loaded + job.delivery_service
                        completions.append((time, job.release))
                        moves += approach + loaded
                        position = job.delivery
                    moves += router.distance(position, home, vehicle)
                values = (
                    max(value for value, _ in completions),
                    sum(value - release for value, release in completions) / 3,
                    moves,
                )
                exact = [min(old, value) for old, value in zip(exact, values)]
        for key, optimum in zip(("T", "R", "D"), exact):
            self.assertLessEqual(bounds[key], optimum)
        result = run(scene)
        self.assertTrue(result["feasible"])
        self.assertTrue(validate(scene, result))
        for key, actual in zip(
            ("T", "R", "D"),
            (result["makespan"], result["mean_flow_time"], result["moves"]),
        ):
            self.assertLessEqual(bounds[key], actual)

    def test_v91_two_sides_vehicle_restrictions_and_layers(self):
        for seed in (10, 12):
            scene = generate_current(
                size="medium",
                seed=seed,
                task_count=4,
                vehicles=2,
                shelf_layers=8,
                arrival="uniform",
            )
            before = scene.to_dict()
            bounds = lower_bounds(scene)
            result = run_sipp(scene, policy="greedy")
            self.assertTrue(result["feasible"])
            self.assertTrue(validate(scene, result))
            self.assertEqual(scene.to_dict(), before)
            self.assertLessEqual(bounds["T"], result["makespan"])
            self.assertLessEqual(bounds["R"], result["mean_flow_time"])
            self.assertLessEqual(bounds["D"], result["moves"])


if __name__ == "__main__":
    unittest.main()
