"""Read-only, retrospective dispatch ledger; never used by an online policy.

Completed-event timestamps and actual paths determine time accounting. Dispatch
waiting cannot be causally split into layer gating, unavailable vehicles, failed
planning and policy choice from final events alone. In particular, stationary
travel intervals are observable waiting, not proof of a traffic bottleneck.
"""

from math import ceil
from statistics import mean, pstdev


def analyze_dispatch(scenario, result):
    """Return exact per-task/fleet ledgers, rejecting inconsistent timestamps.

    Call the independent execution validator first when accepting external data.
    This ledger is a consistency check, not another collision/rule validator.
    Failed executions remain explicitly incomplete and are never success costs.
    """
    jobs = {job.id: job for job in scenario.tasks}
    rows = []
    for event in result["events"]:
        job = jobs[event["task_id"]]
        k = event["vehicle"]
        times = [
            job.release,
            event["assigned_at"],
            event["pickup_arrival"],
            event["pickup_end"],
            event["delivery_arrival"],
            event["delivery_end"],
        ]
        if any(type(t) is not int for t in times) or times != sorted(times):
            raise ValueError("Non-monotone task ledger timestamps")
        release, assigned, pickup, pickup_end, delivery, end = times
        if pickup_end - pickup != job.pickup_service or end - delivery != job.delivery_service:
            raise ValueError("Service duration differs from immutable task")
        path = result["paths"][k]
        if end >= len(path):
            raise ValueError("Task completion outside executed path")

        def movement(a, b):
            return sum(path[t] != path[t + 1] for t in range(a, b))

        empty = movement(assigned, pickup)
        loaded = movement(pickup_end, delivery)
        row = dict(
            task_id=job.id,
            vehicle=k,
            release=release,
            assigned_at=assigned,
            completed_at=end,
            dispatch_wait=assigned - release,
            pickup_duration=pickup - assigned,
            loaded_duration=delivery - pickup_end,
            service_duration=job.pickup_service + job.delivery_service,
            empty_travel_moves=empty,
            empty_stationary_wait=pickup - assigned - empty,
            loaded_travel_moves=loaded,
            loaded_stationary_wait=delivery - pickup_end - loaded,
            flow_time=end - release,
        )
        row["ledger_total"] = sum(
            row[name]
            for name in ("dispatch_wait", "pickup_duration", "loaded_duration", "service_duration")
        )
        row["ledger_residual"] = row["flow_time"] - row["ledger_total"]
        if row["ledger_residual"] != 0:
            raise ValueError("Task ledger does not reconcile")
        rows.append(row)
    flows = sorted(row["flow_time"] for row in rows)
    duration = result["time"]
    fleet = []
    for k, (path, labels) in enumerate(zip(result["paths"], result["interval_states"])):
        events = [event for event in result["events"] if event["vehicle"] == k]
        own = [row for row in rows if row["vehicle"] == k]
        moves = sum(a != b for a, b in zip(path, path[1:]))
        service = sum(state in ("loading", "unloading") for state in labels)
        idle = sum(state == "idle" for state in labels)
        task_busy = sum(row["completed_at"] - row["assigned_at"] for row in own)
        fleet.append(
            dict(
                vehicle=k,
                completed_tasks=len(events),
                last_unload=max((e["delivery_end"] for e in events), default=0),
                executed_duration=len(labels),
                moves=moves,
                service_steps=service,
                idle_steps=idle,
                stationary_nonservice_wait=sum(
                    a == b and state not in ("loading", "unloading", "idle")
                    for a, b, state in zip(path, path[1:], labels)
                ),
                task_busy_steps_completed=task_busy,
                service_utilization=service / duration if duration else 0,
                task_utilization_completed=task_busy / duration if duration else 0,
            )
        )
    busy = [row["task_busy_steps_completed"] for row in fleet]
    completed = len(rows)
    successful = bool(result["feasible"] and completed == len(jobs))
    return dict(
        execution_successful=successful,
        ledger_scope="all_tasks" if successful else "completed_tasks_only",
        total_tasks=len(jobs),
        completed_tasks=completed,
        all_ledgers_reconcile=all(row["ledger_residual"] == 0 for row in rows),
        dispatch_wait_attribution="unidentified: layer gate, vehicle availability, planning rejection and policy delay may overlap",
        means={
            name: mean(row[name] for row in rows) if rows else None
            for name in (
                "dispatch_wait",
                "pickup_duration",
                "loaded_duration",
                "service_duration",
                "empty_travel_moves",
                "empty_stationary_wait",
                "loaded_travel_moves",
                "loaded_stationary_wait",
                "flow_time",
            )
        },
        p90_flow_time=flows[ceil(0.9 * completed) - 1] if flows else None,
        max_flow_time=max(flows) if flows else None,
        workload_cv_completed=pstdev(busy) / mean(busy) if busy and mean(busy) else 0,
        tasks=rows,
        fleet=fleet,
    )
