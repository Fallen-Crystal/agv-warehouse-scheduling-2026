"""第三项：响应时间、任务分解和逐车工作量。仅统计实际执行轨迹。"""

from math import ceil
from statistics import pstdev


def summarize(scenario, result):
    jobs = {j.id: j for j in scenario.tasks}
    task_metrics = []
    for r in result["events"]:
        j = jobs[r["task_id"]]
        point = r.get("pickup_point", j.pickup)
        task_metrics.append(
            dict(
                task_id=j.id,
                vehicle=r["vehicle"],
                release=j.release,
                assigned_at=r["assigned_at"],
                completed_at=r["delivery_end"],
                flow_time=r["delivery_end"] - j.release,
                dispatch_wait=r["assigned_at"] - j.release,
                pickup_duration=r["pickup_arrival"] - r["assigned_at"],
                loaded_duration=r["delivery_arrival"] - r["pickup_end"],
                service_duration=j.pickup_service + j.delivery_service,
                pickup_x=point[0],
                pickup_y=point[1],
                shelf_x=j.shelf[0] if j.shelf else None,
                shelf_y=j.shelf[1] if j.shelf else None,
            )
        )
        if scenario.is_v4:
            rack = next(
                v for v in scenario.map_info["rack_catalog"] if tuple(v["position"]) == j.shelf
            )
            task_metrics[-1].update(
                shelf_level=j.shelf_level,
                rack_bay=rack["bay_id"],
                storage_id=f"{rack['bay_id']}-L{j.shelf_level:02d}",
            )
    flows = sorted(j["flow_time"] for j in task_metrics)
    empty_value = 0 if not jobs else None

    def mean(name):
        return (
            sum(j[name] for j in task_metrics) / len(task_metrics) if task_metrics else empty_value
        )

    vehicles = []
    for k, (path, labels) in enumerate(zip(result["paths"], result["interval_states"])):
        row = dict(
            vehicle=k,
            assigned_tasks=sum(r["vehicle"] == k for r in result["assignments"]),
            completed_tasks=sum(r["vehicle"] == k for r in result["events"]),
            moves=0,
            empty_moves=0,
            loaded_moves=0,
            service_steps=0,
            idle_steps=0,
            traffic_wait_steps=0,
            task_busy_steps=0,
        )
        for a, b, state in zip(path, path[1:], labels):
            if state not in ("idle", "returning"):
                row["task_busy_steps"] += 1
            if a != b:
                row["moves"] += 1
                row["loaded_moves" if state == "to_delivery" else "empty_moves"] += 1
            elif state in ("loading", "unloading"):
                row["service_steps"] += 1
            elif state == "idle":
                row["idle_steps"] += 1
            else:
                row["traffic_wait_steps"] += 1
        row["task_utilization"] = row["task_busy_steps"] / result["time"] if result["time"] else 0
        vehicles.append(row)
    busy = [v["task_busy_steps"] for v in vehicles]
    average_busy = sum(busy) / len(busy)
    return dict(
        comparison_valid=result["feasible"],
        metrics_scope="all_tasks" if len(task_metrics) == len(jobs) else "completed_tasks_only",
        response_sample_count=len(task_metrics),
        completion_rate=len(task_metrics) / len(jobs) if jobs else 1,
        max_flow_time=max(flows) if flows else empty_value,
        p90_flow_time=flows[ceil(0.9 * len(flows)) - 1] if flows else empty_value,
        mean_dispatch_wait=mean("dispatch_wait"),
        mean_pickup_duration=mean("pickup_duration"),
        mean_loaded_duration=mean("loaded_duration"),
        mean_service_duration=mean("service_duration"),
        empty_moves=sum(v["empty_moves"] for v in vehicles),
        loaded_moves=sum(v["loaded_moves"] for v in vehicles),
        workload_cv=pstdev(busy) / average_busy if average_busy else 0,
        per_vehicle=vehicles,
        task_metrics=task_metrics,
    )
