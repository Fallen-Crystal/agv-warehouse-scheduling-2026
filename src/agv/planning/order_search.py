"""Static order-search tools. Exact claims apply ONLY to one-car closed static jobs.

No reservations are relaxed in an actual execution. Multi-car costs below are
heuristic candidate filters; the real SIPP rollout decides which plan to use.
"""

import random
from fractions import Fraction
from functools import lru_cache
from math import lcm

from agv.planning.astar import Router


def exact_single(s, normalization=None):
    """Held-Karp DP, exact for static, zero-release, one-car V9.1, <=14 jobs.

    Every order ends at a prescribed D. With one car and no future releases,
    waiting/detours cannot improve T, sum(C), or D. Shortest approach+loaded
    trips dominate all longer trips, including legal choices of loading side.
    A duration increment contributes to every remaining completion time.
    Thus (visited subset, last delivery) is a sufficient Bellman state.
    """
    s.check()
    if (
        not s.is_v9_1
        or len(s.homes) != 1
        or s.order_stream_end != 0
        or s.horizon is not None
        or any(j.release != 0 for j in s.tasks)
        or not 1 <= len(s.tasks) <= 14
    ):
        raise ValueError(
            "Exact reference requires closed zero-release V9.1, one car, 1..14 jobs, no horizon"
        )
    jobs, n, router = list(s.tasks), len(s.tasks), Router(s)
    initial = s.homes[0]
    positions = [j.delivery for j in jobs] + [initial]
    predecessors = []
    for j in jobs:
        predecessors.append(
            sum(
                1 << k
                for k, other in enumerate(jobs)
                if other.shelf == j.shelf
                and (-other.shelf_level, other.id) < (-j.shelf_level, j.id)
            )
        )
    trip = {}
    for last, pos in enumerate(positions):
        for k, j in enumerate(jobs):
            d, point = min(
                (router.distance(pos, p, 0) + router.distance(p, j.delivery, 0), p)
                for p in s.pickup_candidates(j)
            )
            trip[last, k] = (int(d), point)
    back = [int(router.distance(p, initial, 0)) for p in positions]
    # The fixed distance-greedy baseline is analytically reproducible for this
    # supported class; no hidden orders or supplied candidate denominator.
    mask, last, t, cs, distance = 0, n, 0, 0, 0
    while mask != (1 << n) - 1:
        k = min(
            (
                k
                for k in range(n)
                if not mask >> k & 1 and predecessors[k] & mask == predecessors[k]
            ),
            key=lambda k: (
                trip[last, k][0] + jobs[k].pickup_service + jobs[k].delivery_service,
                jobs[k].id,
            ),
        )
        d = trip[last, k][0]
        t += d + jobs[k].pickup_service + jobs[k].delivery_service
        cs += t
        distance += d
        mask, last = mask | 1 << k, k
    reference = normalization or (t, Fraction(cs, n), distance + back[last])
    a, b, c = (
        Fraction(1, 2) / reference[0],
        Fraction(3, 10) / (n * reference[1]),
        Fraction(1, 5) / reference[2],
    )
    scale = lcm(a.denominator, b.denominator, c.denominator)
    ai, bi, ci = (int(x * scale) for x in (a, b, c))
    choices = {}

    @lru_cache(None)
    def dp(mask, last):
        if mask == (1 << n) - 1:
            return ci * back[last]
        best = None
        remaining = n - mask.bit_count()
        for k, j in enumerate(jobs):
            if mask >> k & 1 or predecessors[k] & mask != predecessors[k]:
                continue
            d = trip[last, k][0]
            duration = d + j.pickup_service + j.delivery_service
            value = (ai + bi * remaining) * duration + ci * d + dp(mask | 1 << k, k)
            item = (value, j.id, k)
            if best is None or item < best:
                best = item
        choices[mask, last] = best[2]
        return best[0]

    numerator = dp(0, n)
    mask, last, order, points = 0, n, [], []
    while mask != (1 << n) - 1:
        k = choices[mask, last]
        order.append(jobs[k].id)
        points.append(trip[last, k][1])
        mask, last = mask | 1 << k, k
    return dict(
        order=order,
        pickup_points=points,
        optimal_score=float(Fraction(numerator, scale)),
        exact_numerator=numerator,
        exact_denominator=scale,
        states=dp.cache_info().currsize,
        reference=[float(x) for x in reference],
        scope="one_vehicle_closed_static_full_grid",
    )


class OrderCosts:
    """Reservation-free scheduling proxy, constructed only from an observation."""

    def __init__(self, observation, scenario):
        self.obs, self.s = observation, scenario
        self.router = Router(scenario)
        self.jobs = {j["id"]: j for j in observation["pending"]}
        self.dist = {}

    def trip(self, vehicle, position, job):
        key = (vehicle, tuple(position), job["id"])
        if key not in self.dist:
            j = next(j for j in self.s.tasks if j.id == job["id"])
            self.dist[key] = min(
                self.router.distance(tuple(position), p, vehicle)
                + self.router.distance(p, tuple(job["delivery"]), vehicle)
                for p in self.s.pickup_candidates(j)
            )
        return self.dist[key]

    def estimate(self, order):
        now = self.obs["time"]
        times, positions, completions, moves = [], [], [], 0
        for v in self.obs["vehicles"]:
            record = v["route_record"]
            if v["available"]:
                times.append(now)
                positions.append(tuple(v["position"]))
            else:
                times.append(record["delivery_end"])
                positions.append(tuple(v["active_task"]["delivery"]))
                completions.append(record["delivery_end"] - v["active_task"]["release"])
        pending = list(order)
        face_end = {}
        clock = now
        while pending:
            available = [k for k, t in enumerate(times) if t <= clock]
            did = False
            for job_id in pending[:]:
                j = self.jobs[job_id]
                face = tuple(j["shelf"]) if j.get("shelf") else None
                if face_end.get(face, 0) > clock or any(
                    self.jobs[k].get("shelf") == j.get("shelf")
                    and (-self.jobs[k]["shelf_level"], self.jobs[k]["release"], k)
                    < (-j["shelf_level"], j["release"], job_id)
                    for k in pending
                    if k != job_id
                ):
                    continue
                if not available:
                    break
                k = min(available, key=lambda v: (self.trip(v, positions[v], j), v))
                d = self.trip(k, positions[k], j)
                finish = clock + d + j["pickup_service"] + j["delivery_service"]
                face_end[face] = clock + j["pickup_service"]  # optimistic proxy only
                times[k], positions[k] = finish, tuple(j["delivery"])
                completions.append(finish - j["release"])
                moves += d
                available.remove(k)
                pending.remove(job_id)
                did = True
            if not did:
                events = [t for t in times + list(face_end.values()) if t > clock]
                if not events:
                    return (float("inf"),) * 3
                clock = min(events)
        moves += sum(self.router.distance(p, self.s.homes[k], k) for k, p in enumerate(positions))
        return max(times, default=now) - now, sum(completions) / max(1, len(completions)), moves

    def search(self, *, seed=0, population=16, generations=12):
        """Permutation GA: tournament selection, order crossover, swap mutation.

        Elitism preserves the best proxy candidate. It gives no approximation
        guarantee; candidates are subsequently checked by true SIPP rollouts.
        """
        ids = list(self.jobs)
        if len(ids) < 2:
            return [ids]
        rng = random.Random(seed)
        base = self.estimate(ids)
        scales = [max(1, x) for x in base]
        cache = {}

        def fitness(order):
            key = tuple(order)
            if key not in cache:
                cache[key] = sum(
                    w * v / d for w, v, d in zip((0.5, 0.3, 0.2), self.estimate(order), scales)
                )
            return cache[key], key

        pool = [ids, ids[::-1], sorted(ids, key=lambda k: (self.jobs[k]["release"], k))]
        while len(pool) < population:
            pool.append(rng.sample(ids, len(ids)))
        for _ in range(generations):
            pool.sort(key=fitness)
            new = pool[:2]
            while len(new) < population:
                a = min(rng.sample(pool, 3), key=fitness)
                b = min(rng.sample(pool, 3), key=fitness)
                left, right = sorted(rng.sample(range(len(ids) + 1), 2))
                segment = a[left:right]
                rest = [x for x in b if x not in segment]
                child = rest[:left] + segment + rest[left:]
                if rng.random() < 0.5:
                    i, j = rng.sample(range(len(ids)), 2)
                    child[i], child[j] = child[j], child[i]
                new.append(child)
            pool = new
        ranked = sorted(cache, key=lambda k: (cache[k], k))
        return [list(k) for k in ranked[:4]]
