"""独立检查实际轨迹与事件；不使用规划器的预约表。"""

from math import isclose, isfinite


def _same_metrics(actual, expected):
    """Strict structural/numeric comparison; bool is never a numeric counter."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_same_metrics(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same_metrics(a, b) for a, b in zip(actual, expected))
        )
    if type(expected) is int:
        return type(actual) is int and actual == expected
    if type(expected) is float:
        return (
            type(actual) in (int, float)
            and isfinite(actual)
            and isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        )
    return type(actual) is type(expected) and actual == expected


def _position_event(result, vehicle, time):
    event = next(
        (
            r
            for r in reversed(result.get("positioning_events", []))
            if r["vehicle"] == vehicle and r["start"] <= time
        ),
        None,
    )
    if event is not None and any(
        r["vehicle"] == vehicle and event["start"] < r["assigned_at"] <= time
        for r in result["assignments"]
    ):
        return None
    return event


def _audit_positioning(scenario, result):
    events = result.get("positioning_events", [])
    if not isinstance(events, list) or (events and not scenario.is_v9_1):
        raise ValueError("Positioning requires V9.1 and an event list")
    seen, previous = set(), -1
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "vehicle",
            "start",
            "arrival",
            "target",
            "return_end",
        }:
            raise ValueError("Invalid positioning event")
        k, start, arrival, end = (
            event[key] for key in ("vehicle", "start", "arrival", "return_end")
        )
        if any(type(x) is not int for x in (k, start, arrival, end)) or not (
            0 <= k < len(scenario.homes)
            and 0 <= start <= result["time"]
            and start <= arrival <= end
        ):
            raise ValueError("Invalid positioning timing")
        if (
            start < previous
            or (k, start) in seen
            or (scenario.horizon is not None and end > scenario.horizon)
        ):
            raise ValueError("Duplicate, unordered or out-of-horizon positioning event")
        seen.add((k, start))
        previous = start
        raw = event["target"]
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) != 2
            or any(type(x) is not int for x in raw)
        ):
            raise ValueError("Invalid positioning target")
        target = tuple(raw)
        if target != scenario.homes[k] and (
            target not in scenario.transit_only
            or target in scenario.homes
            or target in scenario.stations
            or target in scenario.pickup_zones
            or not scenario.free(target)
        ):
            raise ValueError("Positioning target is not ordinary floor")
        if any(
            r["vehicle"] == k and r["assigned_at"] <= start < r["delivery_end"]
            for r in result["assignments"]
        ):
            raise ValueError("Positioning interrupted a committed order")
        interruptions = [
            r["assigned_at"]
            for r in result["assignments"]
            if r["vehicle"] == k and r["assigned_at"] > start
        ]
        interruptions += [r["start"] for r in events if r["vehicle"] == k and r["start"] > start]
        cutoff = min(interruptions, default=result["time"] + 1)
        if (
            arrival < cutoff
            and arrival <= result["time"]
            and tuple(result["paths"][k][arrival]) != target
        ):
            raise ValueError("Positioning arrival disagrees with trajectory")
        if cutoff > result["time"] and result.get("feasible") and end > result["time"]:
            raise ValueError("Positioning fallback lies beyond complete execution")
        if (
            end < cutoff
            and end <= result["time"]
            and tuple(result["paths"][k][end]) != scenario.homes[k]
        ):
            raise ValueError("Positioning fallback did not reach own home")


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
        position = _position_event(result, k, a)
        position_support = (
            position is not None and position["arrival"] <= a and b <= position["return_end"]
        )
        if (latest is None and not position_support) or (
            latest is not None
            and (latest["delivery_end"] > a or (b > latest["return_end"] and not position_support))
        ):
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

    require(isinstance(result, dict), "Result must be an object")
    for name in (
        "completed",
        "total_tasks",
        "makespan",
        "moves",
        "service_steps",
        "idle_steps",
        "traffic_wait_steps",
        "response_sample_count",
    ):
        require(
            type(result.get(name)) is int and result[name] >= 0, "Invalid integer metric: " + name
        )
    for name in ("feasible", "comparison_valid"):
        require(type(result.get(name)) is bool, "Invalid boolean flag: " + name)
    for name in ("mean_completion", "mean_flow_time"):
        value = result.get(name)
        require(
            type(value) in (int, float) and isfinite(value) and value >= 0,
            "Invalid numeric metric: " + name,
        )
    require(
        all(key in result for key in ("paths", "time", "assignments", "events", "interval_states")),
        "Missing execution fields",
    )
    raw_paths = result["paths"]
    horizon = result["time"]
    require(
        type(horizon) is int
        and 0 <= horizon
        and (scenario.horizon is None or horizon <= scenario.horizon),
        "Invalid executed time",
    )
    require(
        isinstance(raw_paths, (list, tuple)) and len(raw_paths) == len(scenario.homes),
        "Missing vehicle",
    )
    paths = []
    for path in raw_paths:
        require(
            isinstance(path, (list, tuple)) and len(path) == horizon + 1,
            "Invalid trajectory length",
        )
        normalized = []
        for point in path:
            require(
                isinstance(point, (list, tuple))
                and len(point) == 2
                and all(type(value) is int for value in point),
                "Trajectory coordinates must be pairs of integers",
            )
            normalized.append(tuple(point))
        paths.append(normalized)
    # All subsequent checks share coordinate identity, without changing the caller's data.
    result = {**result, "paths": paths}
    labels = result["interval_states"]
    require(
        isinstance(labels, (list, tuple)) and len(labels) == len(paths),
        "Invalid state vehicle count",
    )
    states = {"idle", "returning", "standby", "to_pickup", "loading", "to_delivery", "unloading"}
    require(
        all(
            isinstance(row, (list, tuple))
            and len(row) == horizon
            and all(type(label) is str and label in states for label in row)
            for row in labels
        ),
        "Invalid interval states",
    )
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
    require(
        isinstance(assignments, list) and all(isinstance(r, dict) for r in assignments),
        "Assignments must be an event list",
    )
    require(isinstance(result["events"], list), "Completed events must be a list")
    if assignments:
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
    if scenario.is_v9:
        require(
            all(r["return_arrival"] == r["return_end"] for r in assignments),
            "Return arrival and end must be the same zero-service event",
        )
    require(
        all(a["assigned_at"] <= b["assigned_at"] for a, b in zip(assignments, assignments[1:])),
        "Assignments must be chronological; same-tick order is the submitted batch order",
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
                isinstance(raw_point, (tuple, list))
                and len(raw_point) == 2
                and all(type(v) is int for v in raw_point),
                "Missing integer pickup point",
            )
            chosen = tuple(raw_point)
            require(
                chosen in scenario.pickup_candidates(j), "Pickup is not an allowed shelf neighbor"
            )
            if "shelf" in r:
                require(
                    r["shelf"] is None
                    or (
                        isinstance(r["shelf"], (tuple, list))
                        and len(r["shelf"]) == 2
                        and all(type(v) is int for v in r["shelf"])
                    ),
                    "Invalid shelf metadata",
                )
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
    _audit_positioning(scenario, result)
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
                cutoff = min(
                    (
                        e["start"]
                        for e in result.get("positioning_events", [])
                        if e["vehicle"] == k and e["start"] >= end
                    ),
                    default=horizon,
                )
                require(
                    tuple(path[end]) == scenario.homes[k]
                    and all(tuple(p) == scenario.homes[k] for p in path[end : cutoff + 1]),
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
    if scenario.is_v9_1 and complete:
        ready = max(
            scenario.order_stream_end, max((r["delivery_end"] for r in expected_events), default=0)
        )
        terminal = next(
            t
            for t in range(ready, horizon + 1)
            if all(path[t] == home for path, home in zip(paths, scenario.homes))
        )
        require(horizon == terminal, "Executed time exceeds actual terminal completion")
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
                position = _position_event(result, k, t)
                fallback_end = max(
                    latest["return_end"] if latest else 0, position["return_end"] if position else 0
                )
                is_idle = t >= fallback_end or t in standby[k]
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
    # Independently rebuild each displayed interval, rather than trusting its label.
    for k in range(len(paths)):
        own = [r for r in assignments if r["vehicle"] == k]
        for t, label in enumerate(labels[k]):
            active = next((r for r in own if r["assigned_at"] <= t < r["delivery_end"]), None)
            if active:
                expected = (
                    "to_pickup"
                    if t < active["pickup_arrival"]
                    else "loading"
                    if t < active["pickup_end"]
                    else "to_delivery"
                    if t < active["delivery_arrival"]
                    else "unloading"
                )
            elif t in standby[k]:
                expected = "standby"
            else:
                latest = next((r for r in reversed(own) if r["assigned_at"] <= t), None)
                pos = _position_event(result, k, t)
                end = max(latest["return_end"] if latest else 0, pos["return_end"] if pos else 0)
                expected = (
                    "returning"
                    if t < end or (end == 0 and paths[k][t] != paths[k][t + 1])
                    else "idle"
                )
            require(label == expected, "State label disagrees with execution phase")
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
        require(_same_metrics(actual, expected), message)

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
    require(_same_metrics(result["task_metrics"], expected_tasks), "Wrong task metric rows")
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
                position = _position_event(result, k, t)
                fallback_end = max(
                    latest["return_end"] if latest else 0, position["return_end"] if position else 0
                )
                row[
                    "idle_steps" if t >= fallback_end or t in standby[k] else "traffic_wait_steps"
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
