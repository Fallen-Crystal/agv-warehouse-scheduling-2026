"""Derive result metrics only from a detached execution trace and scene.

No world state or execution implementation is read here. The validator remains
an independent implementation of trace legality and metric consistency.
"""

from copy import deepcopy

from agv.evaluation.diagnostics import summarize_failures
from agv.evaluation.metrics import summarize


def build_result(scenario, trace):
    records = [deepcopy(r) for r in trace["records"] if r["delivery_end"] <= trace["time"]]
    completions = [r["delivery_end"] for r in records]
    flow = [r["delivery_end"] - trace["jobs"][r["task_id"]].release for r in records]
    moves = service = idle = traffic_wait = 0
    for path, labels in zip(trace["paths"], trace["interval_states"]):
        for a, b, state in zip(path, path[1:], labels):
            if a != b:
                moves += 1
            elif state in ("loading", "unloading"):
                service += 1
            elif state in ("idle", "standby"):
                idle += 1
            else:
                traffic_wait += 1
    result = dict(
        feasible=trace["done"],
        reason=None
        if trace["done"]
        else ("horizon_exhausted" if trace["time"] == scenario.horizon else "unfinished"),
        time=trace["time"],
        completed=len(records),
        total_tasks=len(trace["jobs"]),
        makespan=max(completions, default=0),
        mean_completion=sum(completions) / len(records) if records else 0,
        mean_flow_time=sum(flow) / len(flow) if flow else 0,
        moves=moves,
        service_steps=service,
        idle_steps=idle,
        traffic_wait_steps=traffic_wait,
        paths=deepcopy(trace["paths"]),
        interval_states=deepcopy(trace["interval_states"]),
        events=records,
        assignments=deepcopy(trace["records"]),
    )
    if scenario.is_v9_1:
        result.update(
            order_stream_closed=trace["stream_closed"],
            stream_closed_at=trace["stream_closed_at"],
            idle_policy="stream",
        )
        if trace["positioning"]:
            result["positioning_events"] = deepcopy(trace["position_events"])
    if scenario.is_v9:
        result["idle_waits"] = deepcopy(trace["idle_waits"])
        result["idle_hold_steps"] = trace["idle_hold_steps"]
    result["replanning_events"] = deepcopy(trace["replans"])
    result["routing_stats"] = deepcopy(trace["routing_stats"])
    result.update(summarize(scenario, result))
    if trace["execution_error"]:
        result["reason"] = trace["execution_error"]["kind"]
    result["diagnostics"] = summarize_failures(
        scenario, result, deepcopy(trace["planning_failures"]), trace["execution_error"]
    )
    return result
