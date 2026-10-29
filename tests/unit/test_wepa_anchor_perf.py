"""Behavior-preserving reservation optimizations and opt-in search composition."""

import random
import unittest

from agv.planning.astar import Router
from agv.planning.sipp import SafeIntervalRouter
from agv.policy.wepa.profiles import PROFILES
from agv.warehouse.scenarios import Scenario
from agv.world.reservations import ReservationTable


class ReservationAccelerationTests(unittest.TestCase):
    def test_materialization_is_reused_then_invalidated_after_route_changes(self):
        table = ReservationTable([[(0, 0)], [(1, 0), (2, 0), (3, 0)]], 0)
        vertices, edges = table.view_excluding(0, 0)
        first = edges.materialized()
        self.assertEqual(first, frozenset(edges))
        self.assertIs(first, edges.materialized())
        table.hold(1, 0, 2)
        second = edges.materialized()
        self.assertIsNot(first, second)
        self.assertEqual(second, frozenset(edges))
        self.assertEqual(vertices.end_time(), 4)
        table.replace(1, [(2, 0)], 0)
        self.assertEqual(edges.materialized(), frozenset())
        self.assertEqual(vertices.end_time(), 0)
        self.assertEqual(first, frozenset({(0, (1, 0), (2, 0)), (1, (2, 0), (3, 0))}))

    def test_indexed_horizon_paths_and_search_counts_match_materialized_reference(self):
        rng = random.Random(20261029)
        scene = Scenario(6, 4, {(3, 2)}, set(), [(0, 0), (5, 3)], [], None).check()
        for _ in range(30):
            path = [(5, 3)]
            for _ in range(20):
                path.append(rng.choice([path[-1], *scene.neighbors(path[-1])]))
            table = ReservationTable([[(0, 0)], path], 0)
            for start in (0, 4, 22):
                vertices, edges = table.view_excluding(0, start)
                for kind in (Router, SafeIntervalRouter):
                    indexed, reference = kind(scene), kind(scene)
                    args = ((0, 0), (4, 2), start, 0)
                    expected = reference.leg(*args, set(vertices), set(edges), service=2)
                    actual = indexed.leg(*args, vertices, edges, service=2)
                    self.assertEqual(actual, expected)
                    self.assertEqual(indexed.stats, reference.stats)

    def test_anchor_tail_composes_existing_opt_in_flags(self):
        self.assertEqual(PROFILES["gate_anchor_tail"], dict(PROFILES["gate_anchor"], tail=True))
        self.assertNotIn("tail", PROFILES["gate_anchor"])
        self.assertNotIn("second_anchor", PROFILES["gate_tail"])


if __name__ == "__main__":
    unittest.main()
