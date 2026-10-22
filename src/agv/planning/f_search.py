"""Proposal search only. The official three-term evaluation never changes."""

import math
import random

from agv.core import Task
from agv.planning.astar import Router


def match_batch(vehicles, jobs, cost):
    """Exact max-cardinality min-cost assignment for this fixed visible batch."""
    states = {0: (0, ())}
    for job in jobs:
        updated = dict(states)
        for mask, (value, pairs) in states.items():
            for i, vehicle in enumerate(vehicles):
                if mask >> i & 1:
                    continue
                edge = cost(vehicle, job)
                if not math.isfinite(edge):
                    continue
                new = mask | 1 << i
                item = value + edge, pairs + ((vehicle["id"], job["id"]),)
                if new not in updated or item < updated[new]:
                    updated[new] = item
        states = updated
    best = min(states, key=lambda m: (-m.bit_count(), states[m]))
    return list(states[best][1])


class ProposalCosts:
    """Visible-work list schedule with arrival-aware pickup lock estimates."""

    def __init__(self, observation, scenario, *, matching=True, calibrated=True):
        self.obs, self.s = observation, scenario
        self.s.tasks = [
            Task(
                **{
                    **{
                        k: v
                        for k, v in j.items()
                        if k not in ("dispatchable", "dispatch_block_reason")
                    },
                    "pickup": tuple(j["pickup"]) if j["pickup"] else None,
                    "shelf": tuple(j["shelf"]) if j["shelf"] else None,
                    "delivery": tuple(j["delivery"]),
                }
            )
            for j in observation["pending"]
        ]
        self.jobs = {j["id"]: j for j in observation["pending"]}
        self.task = {j.id: j for j in self.s.tasks}
        self.router = Router(scenario)
        self.cache = {}
        self.matching, self.calibrated = matching, calibrated

    def details(self, vehicle, position, job):
        key = vehicle, tuple(position), job["id"]
        if key not in self.cache:
            task = self.task[job["id"]]
            total, approach, point = min(
                (
                    self.router.distance(tuple(position), p, vehicle)
                    + self.router.distance(p, task.delivery, vehicle),
                    self.router.distance(tuple(position), p, vehicle),
                    p,
                )
                for p in self.s.pickup_candidates(task)
            )
            self.cache[key] = total, approach, point
        return self.cache[key]

    def batch(self, vehicles, jobs):
        def cost(v, j):
            return self.details(v["id"], v["position"], j)[0]

        if self.matching:
            return match_batch(vehicles, jobs, cost)
        available, pairs = list(vehicles), []
        for j in jobs:
            if not available:
                break
            v = min(available, key=lambda v: (cost(v, j), v["id"]))
            pairs.append((v["id"], j["id"]))
            available.remove(v)
        return pairs

    def estimate(self, order):
        now = self.obs["time"]
        times, positions, flows, face_end = [], [], [], {}
        for v in self.obs["vehicles"]:
            if v["available"]:
                times.append(now)
                positions.append(tuple(v["position"]))
            else:
                r = v["route_record"]
                j = v["active_task"]
                times.append(r["delivery_end"])
                positions.append(tuple(j["delivery"]))
                flows.append(r["delivery_end"] - j["release"])
                if self.calibrated:
                    face = tuple(j["shelf"])
                    face_end[face] = max(face_end.get(face, 0), r["pickup_end"])
        pending, clock, moves = list(order), now, 0
        while pending:
            available = [
                dict(id=k, position=positions[k]) for k, t in enumerate(times) if t <= clock
            ]
            ready = []
            for jid in pending:
                j = self.jobs[jid]
                face = tuple(j["shelf"])
                if face_end.get(face, 0) > clock:
                    continue
                if any(
                    self.jobs[p]["shelf"] == j["shelf"]
                    and (-self.jobs[p]["shelf_level"], self.jobs[p]["release"], p)
                    < (-j["shelf_level"], j["release"], jid)
                    for p in pending
                    if p != jid
                ):
                    continue
                ready.append(j)
            batch = ready[: len(available)]
            pairs = self.batch(available, batch)
            for k, jid in pairs:
                j = self.jobs[jid]
                distance, approach, _ = self.details(k, positions[k], j)
                finish = clock + distance + j["pickup_service"] + j["delivery_service"]
                face_end[tuple(j["shelf"])] = (
                    clock + j["pickup_service"] + (approach if self.calibrated else 0)
                )
                times[k], positions[k] = finish, tuple(j["delivery"])
                moves += distance
                flows.append(finish - j["release"])
                pending.remove(jid)
            if not pairs:
                events = [t for t in times + list(face_end.values()) if t > clock]
                if not events:
                    return float("inf"), float("inf"), float("inf")
                clock = min(events)
        if self.obs["order_stream_closed"] or not self.calibrated:
            moves += sum(
                self.router.distance(p, self.s.homes[k], k) for k, p in enumerate(positions)
            )
        return max(times, default=now) - now, sum(flows) / max(1, len(flows)), moves


def proposal_search(costs, *, method="ga", terms="TRD", budget=192, seed=0):
    """Same unique-evaluation cap; mask proposal terms, never final score terms."""
    if method not in ("ga", "random", "hybrid") or terms not in (
        "T",
        "R",
        "D",
        "TR",
        "TD",
        "RD",
        "TRD",
    ):
        raise ValueError("Unknown proposal method or terms")
    ids = list(costs.jobs)
    if budget < 3:
        raise ValueError("Proposal budget must be >=3")
    rng, cache = random.Random(seed), {}
    scales = [max(1, v) for v in costs.estimate(ids)]
    weights = [w if c in terms else 0 for c, w in zip("TRD", (0.5, 0.3, 0.2))]
    weight_sum = sum(weights)
    weights = [w / weight_sum for w in weights]
    cap = min(budget, math.factorial(len(ids)))
    genetic_cap = max(3, cap - 48) if method == "hybrid" and cap > 64 else cap

    def fitness(order, limit):
        key = tuple(order)
        if key not in cache:
            if len(cache) >= limit:
                return float("inf"), key
            values = costs.estimate(order)
            cache[key] = sum(w * v / d for w, v, d in zip(weights, values, scales) if w)
        return cache[key], key

    pool = [ids, ids[::-1], sorted(ids, key=lambda k: (costs.jobs[k]["release"], k))]
    while len(pool) < 16:
        pool.append(rng.sample(ids, len(ids)))
    for order in pool:
        fitness(order, genetic_cap)
    if method == "random":
        attempts = 0
        while len(cache) < cap and attempts < 40 * cap:
            fitness(rng.sample(ids, len(ids)), cap)
            attempts += 1
    else:
        for _ in range(12):
            pool.sort(key=lambda x: fitness(x, genetic_cap))
            new = pool[:2]
            while len(new) < 16:
                a = min(rng.sample(pool, 3), key=lambda x: fitness(x, genetic_cap))
                b = min(rng.sample(pool, 3), key=lambda x: fitness(x, genetic_cap))
                if len(ids) < 2:
                    child = list(a)
                else:
                    left, right = sorted(rng.sample(range(len(ids) + 1), 2))
                    segment = a[left:right]
                    rest = [x for x in b if x not in segment]
                    child = rest[:left] + segment + rest[left:]
                    if rng.random() < 0.5:
                        i, j = rng.sample(range(len(ids)), 2)
                        child[i], child[j] = child[j], child[i]
                fitness(child, genetic_cap)
                new.append(child)
            pool = new
        if method == "hybrid" and len(ids) > 1:
            for _ in range(4 * cap):
                if len(cache) >= cap:
                    break
                ranked = sorted(cache, key=lambda k: (cache[k], k))
                child = list(rng.choice(ranked[: min(4, len(ranked))]))
                i, j = rng.sample(range(len(ids)), 2)
                if rng.random() < 0.5:
                    child[i], child[j] = child[j], child[i]
                else:
                    child.insert(j, child.pop(i))
                fitness(child, cap)
    ranked = sorted(cache, key=lambda k: (cache[k], k))
    return [list(k) for k in ranked[:3]], dict(
        unique_evaluations=len(cache), cap=budget, method=method, proposal_terms=terms
    )
