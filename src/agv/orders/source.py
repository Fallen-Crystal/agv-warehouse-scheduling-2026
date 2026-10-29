"""Order sources own the scheduled input, never a reference to the world."""

from dataclasses import dataclass
from typing import Protocol

from agv.core import Task


class OrderSource(Protocol):
    """Publisher-side input; policies never receive this interface."""

    declared_end: int | None

    def publish(self, time: int) -> tuple[Task, ...]: ...

    def close_event(self, time: int) -> bool: ...

    def has_unpublished(self, time: int) -> bool: ...


@dataclass(frozen=True)
class ScheduledOrderSource:
    """Replay the original scenario order without revealing future jobs online.

    ``publish`` may return an already published task. The publisher owns the
    identity set, so sources remain stateless and snapshots can share them.
    """

    tasks: tuple[Task, ...]
    declared_end: int | None = None

    def publish(self, time):
        return tuple(job for job in self.tasks if job.release <= time)

    def close_event(self, time):
        end = self.declared_end
        if end is None:
            end = max((job.release for job in self.tasks), default=0)
        return time >= end

    def has_unpublished(self, time):
        return any(job.release > time for job in self.tasks)
