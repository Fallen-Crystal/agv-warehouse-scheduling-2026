"""Offline static lower bounds for complete, home-returning executions.

These relaxations deliberately inspect the whole scenario. They are evaluation
diagnostics, never an observation feature or a dispatch objective denominator.
The proof and the limits of the relaxation are in
``docs/research/v91-bounds-positioning.md``.
"""

from copy import copy
from math import ceil, inf, isfinite

from agv.planning.astar import Router


def _assignment_cost(costs):
    """Minimum injection cost, with rows <= columns, in O(rows² * columns).

    This is the rectangular Hungarian primal-dual algorithm. Infinite entries
    denote forbidden arcs; a finite replacement is used only internally and a
    selected forbidden arc is rejected. No floating-point epsilon is required:
    graph distances and the resulting potentials are integers.
    """
    if not costs:
        return 0
    n, m = len(costs), len(costs[0])
    if n > m or any(len(row) != m for row in costs):
        raise ValueError("Assignment requires a rectangular matrix with rows <= columns")
    finite = [value for row in costs for value in row if isfinite(value)]
    if not finite:
        raise ValueError("Static assignment relaxation has no finite solution")
    forbidden = (n + 1) * max(finite, default=0) + 1
    matrix = [[value if isfinite(value) else forbidden for value in row] for row in costs]
    u, v, p, way = [0] * (n + 1), [0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minimum, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    current = matrix[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minimum[j]:
                        minimum[j], way[j] = current, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    chosen = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]
    if any(not isfinite(costs[i][j]) for i, j in chosen):
        raise ValueError("Static assignment relaxation has no finite solution")
    return sum(costs[i][j] for i, j in chosen)


def lower_bounds(scenario):
    """Return proven lower bounds on makespan T, mean flow R and total moves D.

    ``D`` includes compulsory final returns, matching this project's complete
    execution metric. ``T`` ends at the last delivery, not at stream closure or
    final return. Static distances respect obstacles, terminal-only delivery
    stations and each vehicle's forbidden other-home cells. Pickup sides are
    minimized only within an actual vehicle's legal task trip.

    A vehicle may move before a task's release: its earliest pickup is bounded
    by ``max(release, distance(initial_home, pickup))``, NOT their sum. That
    initial-distance bound allows passing station cells: earlier jobs could have
    legitimately visited and exited those stations before this job's pickup.
    Resource, collision, layer-order and consistency constraints are relaxed;
    the bound is useful for diagnosis, not an estimate of the attainable optimum.
    Only compare it with a complete independently validated execution.
    """
    scenario.check()
    jobs, homes = scenario.tasks, scenario.homes
    n, m = len(jobs), len(homes)
    if not n:
        return dict(
            method="static-assignment-relaxation-v1",
            scope="offline_complete_home_return",
            T=0,
            R=0.0,
            D=0,
            details=dict(
                tasks=[],
                T_individual=0,
                T_workload=0,
                D_loaded_only=0,
                D_before_last_delivery=0,
                D_closed_assignment=0,
                service_steps=0,
            ),
        )
    router = Router(scenario)
    motion_geometry = copy(scenario)
    motion_geometry.map_info = {**scenario.map_info, "station_access": "relaxed_motion"}
    initial_router = Router(motion_geometry)
    options, task_rows = [], []
    for job in jobs:
        legal = []
        for vehicle, home in enumerate(homes):
            for pickup in scenario.pickup_candidates(job):
                initial = initial_router.distance(home, pickup, vehicle)
                loaded = router.distance(pickup, job.delivery, vehicle)
                if all(isfinite(value) for value in (initial, loaded)):
                    legal.append((vehicle, pickup, initial, loaded))
        if not legal:
            raise ValueError(f"Task {job.id} has no legal static complete trip")
        service = job.pickup_service + job.delivery_service
        completion = min(
            max(job.release, initial) + service + loaded for _, _, initial, loaded in legal
        )
        options.append(legal)
        task_rows.append(
            dict(
                task_id=job.id,
                earliest_completion=completion,
                min_flow=completion - job.release,
                min_loaded_distance=min(loaded for _, _, _, loaded in legal),
            )
        )

    # Sources: vehicle initial homes, then each job's delivery.
    # Columns: each next job (its empty approach + loaded leg), then ending homes.
    # Real per-vehicle task chains embed into this square assignment; disconnected
    # task cycles and inconsistent vehicle choices remain allowed relaxations.
    costs = [[inf] * (n + m) for _ in range(n + m)]
    for target, legal in enumerate(options):
        for vehicle in range(m):
            costs[vehicle][target] = min(
                (
                    router.distance(homes[vehicle], pickup, vehicle) + loaded
                    for v, pickup, _, loaded in legal
                    if v == vehicle
                ),
                default=inf,
            )
        for source, predecessor in enumerate(jobs):
            if source != target:
                costs[m + source][target] = min(
                    router.distance(predecessor.delivery, pickup, vehicle) + loaded
                    for vehicle, pickup, _, loaded in legal
                )
    for vehicle, home in enumerate(homes):
        costs[vehicle][n + vehicle] = 0  # A vehicle may do no tasks at all.
        for source, job in enumerate(jobs):
            costs[m + source][n + vehicle] = router.distance(job.delivery, home, vehicle)

    closed_distance = _assignment_cost(costs)
    # Discard ending-home columns and the required final returns: all retained
    # movement and every service step must fit into m * last-delivery time.
    prefix_distance = _assignment_cost(
        [[costs[source][target] for source in range(n + m)] for target in range(n)]
    )
    service_steps = sum(job.pickup_service + job.delivery_service for job in jobs)
    individual = max(row["earliest_completion"] for row in task_rows)
    workload = ceil((prefix_distance + service_steps) / m)
    return dict(
        method="static-assignment-relaxation-v1",
        scope="offline_complete_home_return",
        T=max(individual, workload),
        R=sum(row["min_flow"] for row in task_rows) / n,
        D=closed_distance,
        details=dict(
            tasks=task_rows,
            T_individual=individual,
            T_workload=workload,
            D_loaded_only=sum(row["min_loaded_distance"] for row in task_rows),
            D_before_last_delivery=prefix_distance,
            D_closed_assignment=closed_distance,
            service_steps=service_steps,
        ),
    )
