"""Task ownership and lifecycle, held once by the execution kernel."""

from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    UNRELEASED = "unreleased"
    PENDING = "pending"
    ASSIGNED = "assigned"
    LOADING = "loading"
    CARRYING = "carrying"
    UNLOADING = "unloading"
    DONE = "done"


@dataclass
class TaskBook:
    jobs: dict
    active: list
    assigned: set = field(default_factory=set)
    records: list = field(default_factory=list)

    def state(self, task_id, time):
        job = self.jobs[task_id]
        if job.release > time:
            return TaskState.UNRELEASED
        if task_id not in self.assigned:
            return TaskState.PENDING
        record = next(r for r in self.records if r["task_id"] == task_id)
        if time < record["pickup_arrival"]:
            return TaskState.ASSIGNED
        if time < record["pickup_end"]:
            return TaskState.LOADING
        if time < record["delivery_arrival"]:
            return TaskState.CARRYING
        if time < record["delivery_end"]:
            return TaskState.UNLOADING
        return TaskState.DONE
