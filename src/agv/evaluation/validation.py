"""独立检查实际轨迹与事件；不使用规划器的预约表。"""

from math import isclose


def _standby_times(scenario, result):
    """Audit recorded holds from trajectories and immutable task timing, not labels."""
    waits = result.get("idle_waits", [])
    if not isinstance(waits, list) or (waits and not scenario.is_v9):
        raise ValueError("Standby requires V9 and a list of intervals")
    times = {k: set() for k in range(len(scenario.homes))}
    for wait in waits:
        if not isinstance(wait, dict) or set(wait) != {"vehicle", "start", "end"}:
            raise ValueError("Invalid standby interval")
        k, a, b = (wait[key] for key in ("vehicle", "start", "end"))
        if any(type(v) is not int for v in (k, a, b)) or not 0 <= k < len(times) or not 0 <= a < b:
            raise ValueError("Invalid standby timing or vehicle")
        own = [r for r in result["assignments"] if r["vehicle"] == k]
        latest = next((r for r in reversed(own) if r["assigned_at"] <= a), None)
        if latest is None or latest["delivery_end"] > a or b > latest["return_end"]:
            raise ValueError("Standby must delay an unloaded vehicle's fallback return")
        if any(a <= r["assigned_at"] < b for r in own):
            raise ValueError("Standby overlaps a new assignment")
        for t in range(a, min(b, result["time"])):
            if t in times[k]:
                raise ValueError("Overlapping standby intervals")
            p = result["paths"][k][t]
            if tuple(p) not in scenario.transit_only or p != result["paths"][k][t + 1]:
                raise ValueError("Standby must be stationary on ordinary transit floor")
            times[k].add(t)
    return times


def validate(scenario, result):
    def require(ok, message):
        if not ok:
            raise ValueError(message)

    paths = result["paths"]
    horizon = result["time"]
    require(
        type(horizon) is int
        and 0 <= horizon
        and (scenario.horizon is None or horizon <= scenario.horizon),
        "Invalid executed time",
    )
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
    if scenario.is_v9:
        timing_fields = (
            "assigned_at",
            "pickup_arrival",
            "pickup_end",
            "delivery_arrival",
            "delivery_end",
            "return_arrival",
            "return_end",
        )
        require(
            all(
                type(r.get(key)) is int and r[key] >= 0
                for r in assignments
                for key in timing_fields
            ),
            "Invalid V9 event time",
        )
        require(
            all(r["return_arrival"] == r["return_end"] for r in assignments),
            "Return arrival and end must be the same zero-service event",
        )
    require(
        all(
            type(r.get("vehicle")) is int
            and 0 <= r["vehicle"] < len(paths)
            and type(r.get("task_id")) is int
            and r["task_id"] in jobs
            for r in assignments
        ),
        "Unknown vehicle or task",
    )
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
                and (scenario.horizon is None or r["return_end"] <= scenario.horizon),
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
    if scenario.uses_layer_rules:
        assigned, previous = set(), []
        for r in assignments:
            job, now = jobs[r["task_id"]], r["assigned_at"]
            # Immutable job identity is authoritative; shelf is optional event metadata.
            same = [old for old in previous if jobs[old["task_id"]].shelf == job.shelf]
            require(
                all(old["pickup_end"] <= now for old in same),
                "Dispatched before previous face pickup finished",
            )
            contenders = [
                j
                for j in scenario.tasks
                if j.shelf == job.shelf and j.release <= now and j.id not in assigned
            ]
            first = min(contenders, key=lambda j: (-j.shelf_level, j.release, j.id))
            require(first.id == job.id, "Wrong per-face layer dispatch order")
            assigned.add(job.id)
            previous.append(r)
        for k, path in enumerate(paths):
            permits = [
                (jobs[r["task_id"]].delivery, r["delivery_arrival"], r["delivery_end"])
                for r in assignments
                if r["vehicle"] == k
            ]
            for t, p in enumerate(path):
                if tuple(p) in scenario.stations:
                    require(
                        any(tuple(p) == station and a <= t <= b for station, a, b in permits),
                        "Delivery station occupied outside unload service",
                    )
    standby = _standby_times(scenario, result)
    if scenario.is_v9:
        # Only the last fallback is still effective. Older returns can have been
        # interrupted by a later assignment before reaching H.
        for k, path in enumerate(paths):
            latest = next((r for r in reversed(assignments) if r["vehicle"] == k), None)
            if latest is not None and result.get("feasible"):
                require(
                    latest["return_end"] <= horizon,
                    "A complete execution cannot claim a future final return",
                )
            if latest is not None and latest["return_end"] <= horizon:
                end = latest["return_end"]
                if scenario.is_v9_1:
                    require(
                        end == 0 or tuple(path[end - 1]) != scenario.homes[k],
                        "Final return time is later than actual home arrival",
                    )
                require(
                    tuple(path[end]) == scenario.homes[k]
                    and all(tuple(p) == scenario.homes[k] for p in path[end:]),
                    "Final return event does not match actual home trajectory",
                )
    # 同货架不同侧可同时装货；地面停靠格互斥已由逐时刻碰撞检查保证。
    expected_events = [r for r in assignments if r["delivery_end"] <= horizon]
    require(result["events"] == expected_events, "Wrong completion events")
    require(
        result["completed"] == len(expected_events) and result["total_tasks"] == len(jobs),
        "Wrong completion count",
    )
    closed = True
    if scenario.is_v9_1:
        closed = horizon >= scenario.order_stream_end
        require(result.get("idle_policy") == "stream", "Wrong V9.1 idle policy")
        if closed:
            require(type(result.get("stream_closed_at")) is int, "Invalid stream close time type")
        require(
            type(result.get("order_stream_closed")) is bool
            and result["order_stream_closed"] == closed,
            "Wrong stream closed flag",
        )
        require(
            result.get("stream_closed_at") == (scenario.order_stream_end if closed else None),
            "Wrong stream close event time",
        )
    complete = (
        closed
        and len(expected_events) == len(jobs)
        and all(tuple(p[-1]) == home for p, home in zip(paths, scenario.homes))
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
                is_idle = latest is None or t >= latest["return_end"] or t in standby[k]
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
                and a["reason"]
                in ("no_route_within_horizon", "no_route_with_current_reservations"),
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
    if "weighted_score" in result or "score_valid" in result:
        from agv.evaluation.objective import validate_score

        validate_score(scenario, result, execution_validated=True)
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
        if scenario.uses_layer_rules:
            job = jobs[r["task_id"]]
            rack = next(
                v for v in scenario.map_info["rack_catalog"] if tuple(v["position"]) == job.shelf
            )
            row.update(
                shelf_level=job.shelf_level,
                rack_bay=rack["bay_id"],
                storage_id=f"{rack['bay_id']}-L{job.shelf_level:02d}",
            )
    require(result["task_metrics"] == expected_tasks, "Wrong task metric rows")
    for name in ("dispatch_wait", "pickup_duration", "loaded_duration", "service_duration"):
        expected = sum(r[name] for r in expected_tasks) / len(events) if events else none_or_zero
        number(result["mean_" + name], expected, "Wrong time decomposition: " + name)
    vehicles = []
    standby = _standby_times(scenario, result)
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
        if scenario.is_v9:
            row["standby_steps"] = len(standby[k])
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
                    if latest is None or t >= latest["return_end"] or t in standby[k]
                    else "traffic_wait_steps"
                ] += 1
        vehicles.append(row)
    require(len(result["per_vehicle"]) == len(vehicles), "Wrong vehicle metric count")
    for actual, expected in zip(result["per_vehicle"], vehicles):
        require(set(actual) == set(expected), "Wrong vehicle metric fields")
        for name, value in expected.items():
            number(actual[name], value, "Wrong per-vehicle metric: " + name)
    if scenario.is_v9:
        require(
            result.get("standby_steps") == sum(map(len, standby.values())), "Wrong standby total"
        )
        for k, labels in enumerate(result["interval_states"]):
            require(
                {t for t, label in enumerate(labels) if label == "standby"} == standby[k],
                "Standby labels differ from actual holds",
            )
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
