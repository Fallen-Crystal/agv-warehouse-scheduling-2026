"""Replan two newly assigned vehicles in reversed priority, holding peers fixed.

No active task from an earlier tick is changed. A candidate is published as one
atomic suffix update only after all-pair reservations and a full visible-work F
preview accept it. This is local prioritized planning, not full MAPF-LNS or CBS.
"""

from agv.policy.wepa.common import values
from agv.policy.wepa.forecast import rollout, snapshot

FIELDS = ("plans", "records", "active", "assigned", "locks")


def delayed_trip(world, k, job, delay):
    if delay == 0:
        return world.trip(k, job)
    vertices, edges = world.table().view_excluding(k, world.time)
    best = None
    for pickup, drop, ps, ds in world.endpoints(job):
        path = [world.plans[k][0]] * delay
        now = world.time + delay
        start = world.plans[k][0]
        stamps = []
        for goal, service in ((pickup, ps), (drop, ds), (world.scene.homes[k], 0)):
            leg = world.router.leg(
                start,
                goal,
                now,
                k,
                vertices,
                edges,
                service=service,
                delivery_station=goal if goal in world.scene.stations else None,
            )
            if leg is None:
                break
            arrival = now + len(leg) - 1 - service
            now += len(leg) - 1
            path.extend(leg if len(path) == delay else leg[1:])
            stamps.append((arrival, now))
            start = goal
        else:
            record = dict(
                task=job["id"],
                vehicle=k,
                slot=world.bound[job["id"]],
                assigned_at=world.time,
                pickup=pickup,
                drop=drop,
                pickup_arrival=stamps[0][0],
                pickup_end=stamps[0][1],
                drop_arrival=stamps[1][0],
                end=stamps[1][1],
            )
            key = record["end"], sum(a != b for a, b in zip(path, path[1:])), pickup, drop
            if world.table().conflict(path, world.time, k) is None and (
                best is None or key < best[0]
            ):
                best = key, path, record
    return None if best is None else best[1:]


def before_action(world):
    return dict(
        plans=[list(p) for p in world.plans], active=list(world.active), locks=dict(world.locks)
    )


class Coordinator:
    def __init__(self, objective, *, max_events=4, cooldown=64):
        self.objective = objective
        self.max_events = max_events
        self.cooldown = cooldown
        self.events = 0
        self.last = -10000
        self.logs = []

    def improve(self, world, pairs, before, continuation=None):
        if (
            len(pairs) < 2
            or self.events >= self.max_events
            or world.time - self.last < self.cooldown
        ):
            return False
        newly = {j: k for k, j in pairs}
        records = {r["task"]: r for r in world.records if r["task"] in newly}
        delay = []
        for jid, k in newly.items():
            r = records[jid]
            duration = min(
                world.router.distance(before["plans"][k][0], a, k)
                + ps
                + world.router.distance(a, b, k)
                + ds
                for a, b, ps, ds in world.endpoints(world.visible[jid])
            )
            delay.append((r["end"] - world.time - duration, r["end"], k, jid))
        delay.sort(reverse=True)
        if delay[0][0] <= 0:
            return False
        selected = {x[3] for x in delay[:2]}
        original = [(k, j) for k, j in pairs if j in selected]
        self.events += 1
        self.last = world.time
        trial = snapshot(world)
        for k, j in original:
            if before["active"][k] is not None or records[j]["assigned_at"] != world.time:
                raise ValueError("Coordinator attempted to alter an existing task")
            trial.plans[k] = list(before["plans"][k])
            trial.active[k] = None
            trial.assigned.remove(j)
            bay = trial.slots[records[j]["slot"]]["bay"]
            if bay in before["locks"]:
                trial.locks[bay] = before["locks"][bay]
            else:
                trial.locks.pop(bay, None)
        trial.records = [r for r in trial.records if r["task"] not in selected]
        calls = trial.router.stats["calls"]
        reordered = list(reversed(original))
        for k, j in reordered:
            job = trial.visible[j]
            if job not in trial.ready():
                self.logs.append(dict(time=world.time, reason="not_ready", accepted=False))
                return False
            proposal = None
            for delay_ticks in (0, 2, 8):
                proposal = delayed_trip(trial, k, job, delay_ticks)
                if proposal is not None:
                    break
            if proposal is None:
                self.logs.append(dict(time=world.time, reason="no_safe_suffix", accepted=False))
                return False
            trial.commit(k, job, proposal)
        local_calls = trial.router.stats["calls"] - calls
        # All unaffected paths and records must remain byte-for-byte equal.
        for k, p in enumerate(world.plans):
            if k not in {car for car, _ in original} and trial.plans[k] != p:
                raise ValueError("Unselected peer route changed")
        for k, p in enumerate(trial.plans):
            if trial.table().conflict(p, trial.time, k) is not None:
                raise ValueError("Atomic candidate has a reservation conflict")
        base, u0 = rollout(world, continuation)
        alternate, u1 = rollout(trial, continuation)
        total = local_calls + u0["route_calls"] + u1["route_calls"]
        if total > 1100:
            raise ValueError("Coordination event exceeded frozen query budget")
        score0 = self.objective.score(values(base)) if base is not None else None
        score1 = self.objective.score(values(alternate)) if alternate is not None else None
        accept = score0 is not None and score1 is not None and score1 < score0 - 1e-12
        self.logs.append(
            dict(
                time=world.time,
                selected=original,
                priority=reordered,
                static_delay=[x[0] for x in delay[:2]],
                route_calls=total,
                base_usage=u0,
                alternate_usage=u1,
                base_score=score0,
                score=score1,
                accepted=accept,
                known_only=True,
                objective_sha256=self.objective.fingerprint,
            )
        )
        if accept:
            for field in FIELDS:
                setattr(world, field, getattr(trial, field))
        return accept
