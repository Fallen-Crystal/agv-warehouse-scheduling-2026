"""Visible-only WEPA state copies and equivalent quiet forecast jumps.

Forecast histories are compressed bookkeeping, never executable audit traces.
The live executor continues to record every physical step through World.advance.
"""

from copy import copy

from agv.world.observation import freeze
from agv.world.wepa import World


class ShadowWorld(World):
    def publish_and_complete(self):
        self._ready_at = None
        return super().publish_and_complete()

    def commit(self, vehicle, job, proposal):
        super().commit(vehicle, job, proposal)
        self._ready_at = None

    def ready(self):
        if getattr(self, "_ready_at", None) == self.time:
            return self._ready_jobs
        top, lower = {}, {}
        for sid in self.stock:
            slot = self.slots[sid]
            top[slot["bay"]] = max(top.get(slot["bay"], 0), slot["level"])
        for sid in self.in_reserved:
            slot = self.slots[sid]
            lower[slot["bay"]] = min(lower.get(slot["bay"], slot["level"]), slot["level"])
        jobs = []
        for job in self.visible.values():
            jid = job["id"]
            if jid in self.assigned or jid not in self.bound:
                continue
            slot = self.slots[self.bound[jid]]
            if self.locks.get(slot["bay"], 0) > self.time:
                continue
            if job["kind"] == "retrieval":
                if top.get(slot["bay"], 0) > slot["level"]:
                    continue
            elif lower.get(slot["bay"], slot["level"]) < slot["level"]:
                continue
            jobs.append(job)
        self._ready_at, self._ready_jobs = self.time, jobs
        return jobs

    def jump_quiet(self):
        # A movable idle suffix may need a one-tick hold, so never jump over it.
        if self.closed and len(self.completed) == len(self.tasks):
            delta = max(len(path) - 1 for path in self.plans)
        elif all(
            record is not None or len(path) == 1 for record, path in zip(self.active, self.plans)
        ):
            events = [
                time
                for record in self.active
                if record is not None
                for time in (record["pickup_end"], record["end"])
                if time > self.time
            ]
            delta = min(events) - self.time if events else 0
        else:
            return False
        if delta <= 1:
            return False
        for vehicle, path in enumerate(self.plans):
            end = min(delta, len(path) - 1)
            self.past_moves += sum(a != b for a, b in zip(path[:end], path[1 : end + 1]))
            self.plans[vehicle] = path[end:]
            self.history[vehicle].append(self.plans[vehicle][0])
        self.time += delta
        return True


def snapshot(world, *, router_factory, fast=True):
    """Detach mutable execution state without carrying future jobs or closure time."""
    view = object.__new__(ShadowWorld if fast else World)
    view.scene, view.slots = world.scene, world.slots
    view.router = router_factory(world.scene)
    view.router.cache = world.router.cache
    view.router.stats = dict(world.router.stats)
    view.tasks = {jid: dict(job) for jid, job in world.visible.items()}
    view.visible = dict(view.tasks)
    view.model = {"close_at": world.time, "tasks": list(view.tasks.values())}
    view.plans = [list(path) for path in world.plans]
    view.history = [[path[0]] for path in view.plans]
    view.labels = [[] for _ in view.plans]
    view.records = list(world.records)
    view.active = list(world.active)
    for field in ("stock", "completed", "assigned", "processed_pickups"):
        setattr(view, field, set(getattr(world, field)))
    for field in ("out_reserved", "in_reserved", "bound", "locks"):
        setattr(view, field, dict(getattr(world, field)))
    view.time, view.closed = world.time, True
    view.decisions, view.holds, view.routing_failures = [], 0, 0
    view.past_moves = world.past_moves
    return view


def _geometry(world):
    if not hasattr(world, "_public_geometry"):
        scene = copy(world.scene)
        for field in ("blocked", "shelves", "pickup_zones", "transit_only"):
            setattr(scene, field, frozenset(getattr(scene, field)))
        for field in ("homes", "stations"):
            setattr(scene, field, freeze(list(getattr(scene, field))))
        scene.tasks = freeze([])
        scene.order_stream_end = None
        scene.map_info = freeze(scene.map_info)
        world._public_geometry = scene
        world._public_slots = freeze(world.slots)
    return world._public_geometry, world._public_slots


class WepaObservation:
    """Explicit public fields and checked commands; no future-stream delegation.

    A successful command refreshes the detached values so one batch can observe
    its earlier commits. Private callbacks are trusted composition plumbing,
    rather than a sandbox against deliberate Python introspection.
    """

    def __init__(self, world):
        self.scene, self.slots = _geometry(world)
        self.router = world.router
        self._trip = world.trip
        self._commit = world.commit
        self._ready = world.ready
        self._endpoints = world.endpoints
        self._estimate = world.estimate
        self._ordinary = world.ordinary
        self._record_routing_failure = world.record_routing_failure

        def refresh():
            self.time, self.closed = world.time, world.closed
            self.visible = freeze({jid: dict(job) for jid, job in world.visible.items()})
            self.tasks = self.visible
            self.model = freeze({"close_at": world.time, "tasks": list(self.visible.values())})
            self.plans = freeze([list(path) for path in world.plans])
            self.records = freeze([dict(record) for record in world.records])
            self.active = freeze([dict(record) if record else None for record in world.active])
            for field in ("stock", "completed", "assigned", "processed_pickups"):
                setattr(self, field, frozenset(getattr(world, field)))
            for field in ("out_reserved", "in_reserved", "bound", "locks"):
                setattr(self, field, freeze(dict(getattr(world, field))))
            self.past_moves = world.past_moves
            self.route_kind = getattr(world, "route_kind", "sipp")
            self.route_seed = getattr(world, "route_seed", 0)
            self.observed_closed = getattr(world, "observed_closed", world.closed)
            self.forecast_terminal = getattr(world, "forecast_terminal", "home")

        self._refresh = refresh
        refresh()

    def ready(self):
        return freeze([dict(job) for job in self._ready()])

    def endpoints(self, job):
        return self._endpoints(job)

    def estimate(self, vehicle, job):
        return self._estimate(vehicle, job)

    def trip(self, vehicle, job):
        return self._trip(vehicle, job)

    def commit(self, vehicle, job, proposal):
        self._commit(vehicle, job, proposal)
        self._refresh()

    def ordinary(self, point):
        return self._ordinary(point)

    def record_routing_failure(self):
        self._record_routing_failure()


def observation(world):
    return WepaObservation(world)
