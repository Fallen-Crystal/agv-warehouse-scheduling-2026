"""独立检查实际轨迹与事件；不使用规划器的预约表。"""

from math import isclose


def validate(scenario, result):
    def require(ok, message):
        if not ok:
            raise ValueError(message)

    paths = result["paths"]
    horizon = result["time"]
    require(0 <= horizon <= scenario.horizon, "Invalid executed time")
    require(len(paths) == len(scenario.homes), "Missing vehicle")
    for k, path in enumerate(paths):
        require(
            len(path) == horizon + 1 and tuple(path[0]) == scenario.homes[k], "Invalid start/length"
        )
        for p in path:
            p = tuple(p)
            require(
                scenario.free(p) and p not in set(scenario.homes) - {scenario.homes[k]},
                "Obstacle or foreign home",
            )
        require(
            all(abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1 for a, b in zip(path, path[1:])),
            "Illegal movement",
        )
    for t in range(horizon + 1):
        current = [tuple(p[t]) for p in paths]
        require(len(set(current)) == len(current), "Vertex collision")
        if t:
            for k in range(len(paths)):
                for peer in range(k):
                    require(
                        not (
                            paths[k][t - 1] == paths[peer][t] and paths[peer][t - 1] == paths[k][t]
                        ),
                        "Edge swap",
                    )
    jobs = {j.id: j for j in scenario.tasks}
    assignments = result["assignments"]
    require(len({r["task_id"] for r in assignments}) == len(assignments), "Duplicate assignment")
    service_intervals = {k: set() for k in range(len(paths))}
    for k in range(len(paths)):
        previous_end = 0
        for r in (r for r in assignments if r["vehicle"] == k):
            require(r["task_id"] in jobs, "Unknown task")
            j = jobs[r["task_id"]]
            require(
                previous_end <= r["assigned_at"] <= horizon and r["assigned_at"] >= j.release,
                "Release or capacity violated",
            )
            require(
                r["assigned_at"]
                <= r["pickup_arrival"]
                <= r["pickup_end"]
                <= r["delivery_arrival"]
                <= r["delivery_end"]
                <= r["return_end"]
                <= scenario.horizon,
                "Invalid task timing",
            )
            raw_point = r.get("pickup_point", j.pickup)
            require(
                isinstance(raw_point, (tuple, list)) and len(raw_point) == 2, "Missing pickup point"
            )
            chosen = tuple(raw_point)
            require(
                chosen in scenario.pickup_candidates(j), "Pickup is not an allowed shelf neighbor"
            )
            if "shelf" in r:
                require(
                    (tuple(r["shelf"]) if r["shelf"] is not None else None) == j.shelf,
                    "Wrong target shelf",
                )
            for name, goal, duration in [
                ("pickup", chosen, j.pickup_service),
                ("delivery", j.delivery, j.delivery_service),
            ]:
                a, b = r[name + "_arrival"], r[name + "_end"]
                require(b - a == duration, "Invalid service duration")
                for t in range(a, min(b, horizon) + 1):
                    require(tuple(paths[k][t]) == goal, "Wrong service position")
                service_intervals[k].update(range(a, min(b, horizon)))
            previous_end = r["delivery_end"]
    require(
        all(type(r["vehicle"]) is int and 0 <= r["vehicle"] < len(paths) for r in assignments),
        "Unknown vehicle",
    )
    # 同货架不同侧可同时装货；地面停靠格互斥已由逐时刻碰撞检查保证。
    expected_events = [r for r in assignments if r["delivery_end"] <= horizon]
    require(result["events"] == expected_events, "Wrong completion events")
    require(
        result["completed"] == len(expected_events) and result["total_tasks"] == len(jobs),
        "Wrong completion count",
    )
    complete = len(expected_events) == len(jobs) and all(
        tuple(p[-1]) == home for p, home in zip(paths, scenario.homes)
    )
    require(result["feasible"] == complete, "Wrong success flag")
    times = [r["delivery_end"] for r in expected_events]
    flow = [r["delivery_end"] - jobs[r["task_id"]].release for r in expected_events]
    require(result["makespan"] == max(times, default=0), "Wrong makespan")
    require(
        isclose(result["mean_completion"], sum(times) / len(times) if times else 0),
        "Wrong mean completion",
    )
    require(
        isclose(result["mean_flow_time"], sum(flow) / len(flow) if flow else 0), "Wrong mean flow"
    )
    moves = service = idle = waiting = 0
    for k, path in enumerate(paths):
        for t, (a, b) in enumerate(zip(path, path[1:])):
            if a != b:
                require(t not in service_intervals[k], "Moved during service")
                moves += 1
            elif t in service_intervals[k]:
                service += 1
            else:
                # 不读取interval_states，通过事件重建执行阶段。
                latest = next(
                    (
                        r
                        for r in reversed(assignments)
                        if r["vehicle"] == k and r["assigned_at"] <= t
                    ),
                    None,
                )
                is_idle = latest is None or t >= latest["return_end"]
                if is_idle:
                    idle += 1
                else:
                    waiting += 1
    require(
        (moves, service, idle, waiting)
        == (
            result["moves"],
            result["service_steps"],
            result["idle_steps"],
            result["traffic_wait_steps"],
        ),
        "Wrong movement metrics",
    )
    validate_metrics(scenario, result)
    if "diagnostics" in result:
        d = result["diagnostics"]
        attempts = d["planning_failures"]
        require(d["planning_failure_count"] == len(attempts), "Wrong failure count")
        for a in attempts:
            require(
                0 <= a["time"] <= horizon
                and a["task_id"] in jobs
                and 0 <= a["vehicle"] < len(paths),
                "Invalid failure record",
            )
            require(
                a["failed_leg"] in ("pickup", "delivery", "return")
                and a["reason"] == "no_route_within_horizon",
                "Invalid failure type",
            )
            require(a["time"] >= jobs[a["task_id"]].release, "Failure for unreleased task")
        require(
            d["planning_failure_by_leg"]
            == {
                leg: sum(a["failed_leg"] == leg for a in attempts)
                for leg in ("pickup", "delivery", "return")
            },
            "Wrong leg failure counts",
        )
        done = {r["task_id"] for r in result["events"]}
        assigned_ids = {r["task_id"] for r in assignments}
        require(
            [row["task_id"] for row in d["unfinished_tasks"]]
            == [j.id for j in scenario.tasks if j.id not in done],
            "Wrong unfinished tasks",
        )
        for row in d["unfinished_tasks"]:
            j = jobs[row["task_id"]]
            own = [a for a in attempts if a["task_id"] == j.id]
            status = (
                "not_released"
                if j.release > horizon
                else "executing"
                if j.id in assigned_ids
                else "waiting_assignment"
            )
            require(
                row["status"] == status
                and row["release"] == j.release
                and row["elapsed_since_release"] == max(0, horizon - j.release),
                "Wrong unfinished state",
            )
            require(
                row["planning_failures"] == len(own)
                and row["last_failed_leg"] == (own[-1]["failed_leg"] if own else None),
                "Wrong unfinished failure summary",
            )
        require(
            d["vehicles_away_from_home"]
            == [k for k, p in enumerate(paths) if tuple(p[-1]) != scenario.homes[k]],
            "Wrong return status",
        )
    return True


def validate_metrics(scenario, result):
    """按事件区间重建工作量，不读取运行时状态标签或调用metrics.summarize。"""

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    def number(actual, expected, message):
        require(
            actual is None
            if expected is None
            else actual is not None and isclose(actual, expected),
            message,
        )

    jobs = {j.id: j for j in scenario.tasks}
    events, assignments, horizon = result["events"], result["assignments"], result["time"]
    flows = sorted(r["delivery_end"] - jobs[r["task_id"]].release for r in events)
    none_or_zero = 0 if not jobs else None
    require(result["comparison_valid"] == result["feasible"], "Wrong comparison validity")
    require(
        result["metrics_scope"]
        == ("all_tasks" if len(events) == len(jobs) else "completed_tasks_only"),
        "Wrong metrics scope",
    )
    require(result["response_sample_count"] == len(events), "Wrong response sample count")
    number(
        result["completion_rate"], len(events) / len(jobs) if jobs else 1, "Wrong completion rate"
    )
    number(result["max_flow_time"], max(flows) if flows else none_or_zero, "Wrong longest response")
    # nearest-rank P90，用整数上取整独立复算。
    number(
        result["p90_flow_time"],
        flows[(9 * len(flows) + 9) // 10 - 1] if flows else none_or_zero,
        "Wrong P90",
    )
    expected_tasks = [
        dict(
            task_id=r["task_id"],
            vehicle=r["vehicle"],
            release=jobs[r["task_id"]].release,
            assigned_at=r["assigned_at"],
            completed_at=r["delivery_end"],
            flow_time=r["delivery_end"] - jobs[r["task_id"]].release,
            dispatch_wait=r["assigned_at"] - jobs[r["task_id"]].release,
            pickup_duration=r["pickup_arrival"] - r["assigned_at"],
            loaded_duration=r["delivery_arrival"] - r["pickup_end"],
            service_duration=jobs[r["task_id"]].pickup_service
            + jobs[r["task_id"]].delivery_service,
        )
        for r in events
    ]
    for row, r in zip(expected_tasks, events):
        point = tuple(r.get("pickup_point", jobs[r["task_id"]].pickup))
        shelf = jobs[r["task_id"]].shelf
        row.update(
            pickup_x=point[0],
            pickup_y=point[1],
            shelf_x=shelf[0] if shelf else None,
            shelf_y=shelf[1] if shelf else None,
        )
    require(result["task_metrics"] == expected_tasks, "Wrong task metric rows")
    for name in ("dispatch_wait", "pickup_duration", "loaded_duration", "service_duration"):
        expected = sum(r[name] for r in expected_tasks) / len(events) if events else none_or_zero
        number(result["mean_" + name], expected, "Wrong time decomposition: " + name)
    vehicles = []
    for k, path in enumerate(result["paths"]):
        own = [r for r in assignments if r["vehicle"] == k]
        busy = set(t for r in own for t in range(r["assigned_at"], min(horizon, r["delivery_end"])))
        loaded = set(
            t for r in own for t in range(r["pickup_end"], min(horizon, r["delivery_end"]))
        )
        services = set(
            t
            for r in own
            for a, b in [
                (r["pickup_arrival"], r["pickup_end"]),
                (r["delivery_arrival"], r["delivery_end"]),
            ]
            for t in range(a, min(b, horizon))
        )
        row = dict(
            vehicle=k,
            assigned_tasks=len(own),
            completed_tasks=sum(r["vehicle"] == k for r in events),
            moves=0,
            empty_moves=0,
            loaded_moves=0,
            service_steps=0,
            idle_steps=0,
            traffic_wait_steps=0,
            task_busy_steps=len(busy),
            task_utilization=len(busy) / horizon if horizon else 0,
        )
        for t, (a, b) in enumerate(zip(path, path[1:])):
            if a != b:
                row["moves"] += 1
                row["loaded_moves" if t in loaded else "empty_moves"] += 1
            elif t in services:
                row["service_steps"] += 1
            else:
                latest = next((r for r in reversed(own) if r["assigned_at"] <= t), None)
                row[
                    "idle_steps"
                    if latest is None or t >= latest["return_end"]
                    else "traffic_wait_steps"
                ] += 1
        vehicles.append(row)
    require(len(result["per_vehicle"]) == len(vehicles), "Wrong vehicle metric count")
    for actual, expected in zip(result["per_vehicle"], vehicles):
        require(set(actual) == set(expected), "Wrong vehicle metric fields")
        for name, value in expected.items():
            number(actual[name], value, "Wrong per-vehicle metric: " + name)
    for name in ("empty_moves", "loaded_moves"):
        require(
            result[name] == sum(v[name] for v in vehicles), "Wrong movement decomposition: " + name
        )
    require(
        result["moves"] == result["empty_moves"] + result["loaded_moves"],
        "Movement totals disagree",
    )
    loads = [v["task_busy_steps"] for v in vehicles]
    average = sum(loads) / len(loads)
    cv = (sum((x - average) ** 2 for x in loads) / len(loads)) ** 0.5 / average if average else 0
    number(result["workload_cv"], cv, "Wrong workload CV")
