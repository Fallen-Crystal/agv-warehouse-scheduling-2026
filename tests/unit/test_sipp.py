import random
import unittest

from agv.domain import Scenario
from agv.planning.astar import Router
from agv.planning.sipp import SafeIntervalRouter


def check_leg(test, path, scenario, start, goal, now, vertices, edges, duration):
    if path is None:
        return
    test.assertEqual(path[0], start)
    test.assertEqual(path[-1], goal)
    test.assertLessEqual(now + len(path) - 1, scenario.horizon)
    for i, p in enumerate(path):
        test.assertTrue(scenario.free(p))
        test.assertNotIn((now + i, p), vertices)
        if i:
            a = path[i - 1]
            test.assertLessEqual(abs(a[0] - p[0]) + abs(a[1] - p[1]), 1)
            test.assertNotIn((now + i - 1, p, a), edges)
    test.assertEqual(path[-duration - 1 :], [goal] * (duration + 1))


class SippTests(unittest.TestCase):
    def test_random_differential_earliest_service_finish(self):
        # Independent time-expanded oracle across 250 reservation patterns.
        rng = random.Random(1701)
        s = Scenario(5, 5, {(2, 2)}, set(), [(0, 0)], [], 24).check()
        cells = [(x, y) for x in range(5) for y in range(5) if s.free((x, y))]
        for case in range(250):
            start, goal = rng.sample(cells, 2)
            now = rng.randrange(4)
            duration = rng.randrange(4)
            vertices = {(rng.randrange(25), rng.choice(cells)) for _ in range(50)}
            edges = set()
            for _ in range(25):
                a = rng.choice(cells)
                b = rng.choice(list(s.neighbors(a)))
                edges.add((rng.randrange(24), a, b))
            service_blocked = {rng.randrange(25) for _ in range(6)}
            a = Router(s).leg(start, goal, now, 0, vertices, edges, duration, service_blocked)
            b = SafeIntervalRouter(s).leg(
                start, goal, now, 0, vertices, edges, duration, service_blocked
            )
            self.assertEqual(None if a is None else len(a), None if b is None else len(b), case)
            check_leg(self, b, s, start, goal, now, vertices, edges, duration)
            if b:
                begin = now + len(b) - 1 - duration
                self.assertTrue(
                    all(t not in service_blocked for t in range(begin, begin + duration))
                )

    def test_waiting_compression_and_edge_reservations(self):
        s = Scenario(3, 1, set(), set(), [(0, 0)], [], 500).check()
        vertices = {(t, (1, 0)) for t in range(1, 401)}
        a, b = Router(s), SafeIntervalRouter(s)
        pa = a.leg((0, 0), (2, 0), 0, 0, vertices, set(), 2)
        pb = b.leg((0, 0), (2, 0), 0, 0, vertices, set(), 2)
        self.assertEqual(len(pa), len(pb))
        self.assertLess(b.stats["expanded"] * 20, a.stats["expanded"])
        check_leg(self, pb, s, (0, 0), (2, 0), 0, vertices, set(), 2)
        # A forbidden reverse edge at t=0 forces a real wait even though both
        # endpoint vertices are free. A vertex-only interval planner is wrong.
        path = b.leg((0, 0), (1, 0), 0, 0, set(), {(0, (1, 0), (0, 0))})
        self.assertEqual(path, [(0, 0), (0, 0), (1, 0)])

    def test_future_service_block_requires_leave_and_reenter_goal(self):
        s = Scenario(3, 2, set(), set(), [(0, 0)], [], 20).check()
        vertices = {(2, (1, 0))}
        a = Router(s).leg((0, 0), (1, 0), 0, 0, vertices, set(), 3)
        b = SafeIntervalRouter(s).leg((0, 0), (1, 0), 0, 0, vertices, set(), 3)
        self.assertEqual(len(a), len(b))
        check_leg(self, b, s, (0, 0), (1, 0), 0, vertices, set(), 3)
        # Later service start inside an otherwise safe goal interval.
        p = SafeIntervalRouter(s).leg((0, 0), (1, 0), 0, 0, set(), set(), 2, {1, 2, 3})
        self.assertEqual(len(p) - 1, 6)

    def test_service_at_horizon_and_blocked_start(self):
        s = Scenario(2, 1, set(), set(), [(0, 0)], [], 4).check()
        r = SafeIntervalRouter(s)
        self.assertEqual(len(r.leg((0, 0), (1, 0), 0, 0, set(), set(), 3)) - 1, 4)
        self.assertIsNone(r.leg((0, 0), (1, 0), 0, 0, {(0, (0, 0))}, set()))
        self.assertIsNone(r.leg((0, 0), (1, 0), 0, 0, set(), set(), 4))
