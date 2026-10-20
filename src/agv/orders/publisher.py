"""Explicit publication/close state, independent of execution and policies."""

from collections.abc import Mapping
from types import MappingProxyType

from agv.core import Task
from agv.orders.source import OrderSource


class OrderPublisher:
    """Manage only the published set and publisher-owned stream close event.

    The world supplies its current time and consumes publication deltas. No
    method mutates a world, route, assignment, or policy object.
    """

    def __init__(self, source: OrderSource, *, manual=False):
        self.source = source
        self.manual = manual
        self._released_jobs: dict[int, Task] = {}
        self.closed = False
        self.closed_at = None

    @property
    def released_jobs(self) -> Mapping[int, Task]:
        return MappingProxyType(self._released_jobs)

    def initialize(self, time=0):
        self._released_jobs = {}
        self.closed = False
        self.closed_at = None
        return self.publish(time)

    def publish(self, time):
        released = []
        for job in self.source.publish(time):
            if job.id not in self._released_jobs:
                released.append(job)
            self._released_jobs[job.id] = job
        if not self.closed and not self.manual and self.source.close_event(time):
            self.close(time)
        return tuple(released)

    def close(self, time):
        if self.closed:
            return False
        if self.source.has_unpublished(time):
            raise ValueError("Cannot close before scheduled orders are published")
        if self.source.declared_end is not None and self.source.declared_end != time:
            raise ValueError("Close event must match declared stream end")
        self.closed = True
        self.closed_at = time
        return True

    def final_return_ready(self, assigned, active):
        return (
            self.closed
            and all(job in assigned for job in self._released_jobs)
            and all(record is None for record in active)
        )
