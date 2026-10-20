"""Ordered, reproducible execution of independent experiment tasks."""

import multiprocessing
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class BatchTask:
    seed: int
    payload: object


def _execute(item):
    worker, task = item
    random.seed(task.seed)
    return worker(task.payload)


def run_batch(tasks, worker, *, workers=1):
    """Yield results in input order; worker failures reach the caller unchanged.

    Workers must be module-level callables and payloads must support pickling.
    A task owns its paired scene, so timing rotation inside it stays intact.
    """
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError("workers must be an integer in 1..32")
    if not callable(worker):
        raise TypeError("worker must be callable")
    items = []
    for task in tasks:
        if not isinstance(task, BatchTask) or type(task.seed) is not int:
            raise TypeError("tasks must be BatchTask values with integer seeds")
        items.append((worker, task))
    if workers == 1:
        # A batch must not change the caller's RNG state.
        state = random.getstate()
        try:
            for item in items:
                yield _execute(item)
        finally:
            random.setstate(state)
        return
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        yield from executor.map(_execute, items)
