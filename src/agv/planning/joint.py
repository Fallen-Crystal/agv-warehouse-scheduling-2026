"""RHCR/LNS-inspired feasible suffix improvement; no future order access.

Full remaining routes remain collision-free. Unlike RHCR, collision checks are
not truncated to a short window. Deterministic bounded prioritized repair is
not complete and does not certify globally optimal task schedules.
"""

import random
from copy import deepcopy
from itertools import islice

from agv.core import Task
from agv.planning import create_router
from agv.planning.pickup import plan_task
from agv.warehouse.scenarios import Scenario
from agv.world.reservations import reservations


def score(plans, records, now):
    # Primary: sum of predicted remaining completion times of assigned jobs.
    # Return duration/moves are secondary; already completed jobs contribute 0.
    return (
        sum(max(0, r["delivery_end"] - now) for r in records if r),
        max((now + len(p) - 1 for p in plans), default=now),
        sum(a != b for p in plans for a, b in zip(p, p[1:])),
    )


def repair_vehicle(s, router, v, now, vertices, edges):
    k, pos = v["id"], tuple(v["position"])
    old = deepcopy(v["route_record"])
    if v["active_task"] is None:
        path = router.leg(pos, s.homes[k], now, k, vertices, edges)
        if path is None:
            return None
        if old is not None:
            old["return_end"] = old["return_arrival"] = now + len(path) - 1
        return path, old
    data = v["active_task"]
    job = Task(
        **{
            **data,
            "pickup": tuple(data["pickup"]) if data["pickup"] else None,
            "delivery": tuple(data["delivery"]),
            "shelf": tuple(data["shelf"]) if data["shelf"] else None,
        }
    )
    if now < old["pickup_arrival"]:
        path, record, failed, _ = plan_task(s, router, job, k, pos, now, vertices, edges)
        if failed:
            return None
        record["assigned_at"] = old["assigned_at"]
        return path, record
    # Loading already begun: preserve position, start/end and chosen shelf side.
    path = [pos]
    if now < old["pickup_end"]:
        path += [pos] * (old["pickup_end"] - now)
    if now < old["delivery_arrival"]:
        legs = [("delivery", job.delivery, job.delivery_service), ("return", s.homes[k], 0)]
    else:
        # Unloading already begun: preserve the complete ongoing service.
        path += [pos] * max(0, old["delivery_end"] - now)
        legs = [("return", s.homes[k], 0)]
    if any((now + i, p) in vertices for i, p in enumerate(path)):
        return None
    for name, goal, service in legs:
        leg = router.leg(
            path[-1],
            goal,
            now + len(path) - 1,
            k,
            vertices,
            edges,
            service,
            delivery_station=job.delivery if name == "delivery" else None,
        )
        if leg is None:
            return None
        path.extend(leg[1:])
        old[name + "_end"] = now + len(path) - 1
        old[name + "_arrival"] = old[name + "_end"] - service
    return path, old


class JointPlanner:
    """Destroy all or a small pair of suffixes, repair in several priorities.

    Candidate plans are accepted only if the explicit lexicographic objective
    improves. The incumbent is a safe fallback after bounded search fails.
    """

    def __init__(
        self,
        attempts=8,
        router_kind="astar",
        neighborhoods="legacy",
        ranker=None,
        trial_budget=None,
        collect=None,
    ):
        if type(attempts) is not int or attempts < 1:
            raise ValueError("attempts must be positive")
        if neighborhoods not in ("legacy", "conflict"):
            raise ValueError("Unknown neighborhood selection")
        if trial_budget is not None and (type(trial_budget) is not int or trial_budget < 2):
            raise ValueError("trial_budget must be at least two")
        self.ranker = ranker
        self.trial_budget = trial_budget
        self.collect = collect
        self.router_kind = router_kind
        self.neighborhoods = neighborhoods
        self.attempts = attempts
        self.router = None

    def conflict_orders(self, vehicles, plans, moving, now):
        """Prioritize interacting, delayed suffixes instead of adjacent IDs.

        Delay is the gap to a reservation-free lower bound, not a claim that
        all slack is traffic-caused. Spatial overlap identifies likely peers;
        all candidates still pass full collision/service validation.
        """
        delays = {}
        cells = {k: set(plans[k]) - set(self.router.s.homes) for k in moving}
        for k in moving:
            v = vehicles[k]
            r = v["route_record"]
            job = v["active_task"]
            if job is None:
                lower = self.router.distance(tuple(v["position"]), self.router.s.homes[k], k)
                remaining = len(plans[k]) - 1
            elif now < r["pickup_arrival"]:
                # Geometry holds no jobs; reconstruct only this visible task.
                task = Task(
                    **{
                        **job,
                        "pickup": tuple(job["pickup"]) if job["pickup"] else None,
                        "shelf": tuple(job["shelf"]) if job["shelf"] else None,
                        "delivery": tuple(job["delivery"]),
                    }
                )
                lower = (
                    min(
                        self.router.distance(tuple(v["position"]), p, k)
                        + self.router.distance(p, task.delivery, k)
                        for p in self.router.s.pickup_candidates(task)
                    )
                    + task.pickup_service
                    + task.delivery_service
                )
                remaining = r["delivery_end"] - now
            else:
                remaining = r["delivery_end"] - now
                lower = max(0, r["pickup_end"] - now) + self.router.distance(
                    tuple(v["position"]), tuple(job["delivery"]), k
                )
                lower += (
                    job["delivery_service"]
                    if now < r["delivery_arrival"]
                    else r["delivery_end"] - now
                )
            delays[k] = max(0, remaining - lower)
        pairs = []
        for i, a in enumerate(moving):
            for b in moving[i + 1 :]:
                overlap = len(cells[a] & cells[b])
                pairs.append((delays[a] + delays[b], overlap, a, b))
        pairs.sort(reverse=True)
        orders = []

        def add(order):
            if order not in orders:
                orders.append(order)

        for _, overlap, a, b in pairs:
            if overlap or delays[a] + delays[b]:
                add(sorted((a, b), key=lambda k: (-delays[k], k)))
                add(list(reversed(orders[-1])))
        ranked = sorted(moving, key=lambda k: (-delays[k], k))
        # Whole-fleet fallback keeps an opportunity for three-way coordination.
        full = [ranked, ranked[::-1]]
        if self.ranker is not None:
            from agv.core.features import features as features

            orders.sort(
                key=lambda order: self.ranker.predict(features(vehicles, plans, order, now)),
                reverse=True,
            )
        budget = self.trial_budget or self.attempts + len(moving) - 1
        selected = orders[:] if self.collect is not None else orders[: max(0, budget - 2)]
        for order in full:
            if order not in selected:
                selected.append(order)
        return selected if self.collect is not None else selected[:budget]

    def propose(self, observation):
        m, now = observation["map"], observation["time"]
        s = Scenario.from_observation_map(m, observation["horizon"])
        if self.router is None or self.router.s.to_dict() != s.to_dict():
            self.router = create_router(self.router_kind, s)
        vehicles = observation["vehicles"]
        plans = [
            [tuple(q) for q in (v["committed_path"] if not v["available"] else v["return_path"])]
            for v in vehicles
        ]
        records = [deepcopy(v["route_record"]) for v in vehicles]
        original = score(plans, records, now)
        best = original
        moving = [v["id"] for v in vehicles if len(plans[v["id"]]) > 1]
        if len(moving) < 2:
            return None
        # Rotate priorities to let a later assigned busy vehicle go first.
        orders = [moving[i:] + moving[:i] for i in range(len(moving))]
        orders += [list(reversed(o)) for o in orders[:]]
        rng = random.Random(now)
        while len(orders) < self.attempts:
            order = moving[:]
            rng.shuffle(order)
            orders.append(order)
        trials = list(islice(orders, self.attempts))
        # Pair neighborhoods retain other vehicles' good routes (LNS idea).
        trials += [[a, b] for a, b in zip(moving, moving[1:])]
        if self.neighborhoods == "conflict":
            trials = self.conflict_orders(vehicles, plans, moving, now)
        for order in trials:
            from agv.core.features import features as features

            row_features = (
                features(vehicles, plans, order, now) if self.collect is not None else None
            )
            candidate = deepcopy(plans)
            updates = deepcopy(records)
            vtx, edg = reservations([p for k, p in enumerate(plans) if k not in order], now)
            # All real start positions are occupied at now, including agents
            # which will be repaired later. Their later suffix is destroyed.
            vtx.update((now, tuple(v["position"])) for v in vehicles)
            frozen = {}
            if self.neighborhoods == "conflict":
                for k in order:
                    v = vehicles[k]
                    rec = v["route_record"]
                    end = (
                        rec["pickup_end"]
                        if v["state"] == "loading"
                        else rec["delivery_end"]
                        if v["state"] == "unloading"
                        else now
                    )
                    frozen[k] = {(t, tuple(v["position"])) for t in range(now, end + 1)}
                    vtx.update(frozen[k])
            okay = True
            for k in order:
                own = (now, tuple(vehicles[k]["position"]))
                vtx.difference_update(frozen.get(k, {own}))
                item = repair_vehicle(s, self.router, vehicles[k], now, vtx, edg)
                vtx.add(own)
                if item is None:
                    okay = False
                    break
                candidate[k], updates[k] = item
                more_v, more_e = reservations([candidate[k]], now)
                vtx.update(more_v)
                edg.update(more_e)
            if self.collect is not None:
                value = score(candidate, updates, now) if okay else None
                gain = (best[0] - value[0]) if okay else -1
                self.collect.append(
                    dict(features=row_features, target=gain, feasible=okay, time=now, order=order)
                )
            if okay:
                value = score(candidate, updates, now)
                if value < best:
                    plans, records, best = candidate, updates, value
        if best >= original:
            return None
        return dict(
            plans=plans, records=records, before=original, after=best, trials=len(trials), time=now
        )
