"""Bounded candidate rollout dispatch, using only a detached observation.

No path, resource, service or offline objective rules are changed here. The
incumbent legal greedy batch is retained when previews fail or exhaust budget.
"""

from dataclasses import asdict
from math import isfinite
from time import perf_counter, process_time

from agv.policy.candidates import legalize, make_batches
from agv.policy.forecast import ShadowState
from agv.policy.greedy import greedy_action

DEFAULT_BUDGET = dict(max_route_calls=480, max_expanded=120000, max_steps=2400)
WEIGHTS = (0.5, 0.3, 0.2)


def fallback(observation):
    if not any(v["available"] for v in observation["vehicles"]) or not any(
        j.get("dispatchable", True) for j in observation["pending"]
    ):
        return []
    return legalize(greedy_action(observation), observation)


def bcrd_action(
    observation,
    max_batches=4,
    depth=None,
    mode="full",
    budget=None,
    diagnostics=None,
    min_queue_ratio=3.0,
    event_driven=True,
    tail_guard=False,
    *,
    world_factory,
):
    """Compare complete visible-world rollouts, with fixed per-decision scales.

    The scales are predictions from the visible greedy rollout, *not* the
    offline same-scene denominators. Zero candidate budget returns safe greedy.
    Truncated previews with residual jobs are rejected in this first version:
    an incomplete forecast cannot win by omitting a difficult order.
    """
    if observation.get("idle_hold_steps", 0) or "positioning_targets" in observation:
        raise ValueError("Standby forecasting requires a separately validated shadow contract")
    if type(tail_guard) is not bool:
        raise ValueError("tail_guard must be boolean")
    if type(event_driven) is not bool:
        raise ValueError("event_driven must be a boolean")
    if type(max_batches) is not int or not 0 <= max_batches <= 32:
        raise ValueError("max_batches must be 0..32")
    if (
        type(min_queue_ratio) not in (int, float)
        or not isfinite(min_queue_ratio)
        or min_queue_ratio < 0
    ):
        raise ValueError("min_queue_ratio must be finite and nonnegative")
    started = perf_counter()
    cpu_started = process_time()
    safe = fallback(observation)
    log = dict(
        time=observation["time"],
        visible_pending=len(observation["pending"]),
        visible_active=sum(not v["available"] for v in observation["vehicles"]),
        candidates=[],
        candidates_generated=0,
        candidate_pool=[],
        chosen="greedy",
        reason="low_pressure",
        shadow_calls=0,
        shadow_route_calls=0,
        shadow_expanded=0,
        fallback=False,
    )

    def finish(action):
        log["issued_pairs"] = [list(pair) for pair in action]
        log["wall_seconds"] = perf_counter() - started
        log["cpu_seconds"] = process_time() - cpu_started
        if diagnostics is not None:
            diagnostics.append(log)
        return action

    legal_queue = sum(j.get("dispatchable", True) for j in observation["pending"])
    available_count = sum(v["available"] for v in observation["vehicles"])
    log.update(legal_queue=legal_queue, available_vehicles=available_count)
    if len(safe) < 2 or max_batches == 0 or legal_queue < min_queue_ratio * available_count:
        log["fallback"] = max_batches == 0
        if max_batches == 0:
            log["reason"] = "candidate_budget"
        return finish(safe)
    limits = {**DEFAULT_BUDGET, **({} if budget is None else budget)}
    if any(limits.get(k, 1) <= 0 for k in ("max_route_calls", "max_expanded", "max_steps")):
        log.update(reason="preview_budget", fallback=True)
        return finish(safe)
    batches = make_batches(observation, max_batches=max_batches, include=safe, mode=mode)
    log["candidates_generated"] = len(batches)
    log["candidate_pool"] = [asdict(batch) for batch in batches]
    shadow = ShadowState.from_observation(
        observation, router_kind="sipp", event_driven=event_driven, world_factory=world_factory
    )
    scales, best, action, incumbent_p90 = None, 1.0, safe, None
    for batch in batches:
        remaining = dict(limits)
        for name, used in (
            ("max_route_calls", log["shadow_route_calls"]),
            ("max_expanded", log["shadow_expanded"]),
        ):
            remaining[name] -= used
        if "max_cpu_seconds" in remaining:
            remaining["max_cpu_seconds"] -= process_time() - cpu_started
        if any(
            remaining.get(k, 1) <= 0 for k in ("max_route_calls", "max_expanded", "max_cpu_seconds")
        ):
            log["reason"] = "decision_budget"
            break
        estimate = shadow.preview(batch.pairs, depth=depth, budget=remaining)
        log["shadow_calls"] += 1
        log["shadow_route_calls"] += estimate["routing_stats"]["calls"]
        log["shadow_expanded"] += estimate["routing_stats"]["expanded"]
        valid = estimate["valid"] and estimate["completed"]
        costs = (
            max(0, estimate["predicted_T"] - observation["time"]),
            estimate["mean_flow_time"],
            estimate["additional_moves"],
        )
        if scales is None and valid:
            scales = tuple(max(1.0, float(value)) for value in costs)
        value = (
            sum(w * c / d for w, c, d in zip(WEIGHTS, costs, scales)) if valid and scales else None
        )
        flows = sorted(observation.get("completed_flow_times", []) + estimate["flow_times"])
        p90 = flows[(9 * len(flows) + 9) // 10 - 1] if flows else 0
        if batch.id == "greedy" and valid:
            incumbent_p90 = p90
        tail_rejected = tail_guard and incumbent_p90 is not None and p90 > incumbent_p90
        log["candidates"].append(
            dict(
                **asdict(batch),
                valid=valid,
                score=value,
                costs=list(costs),
                preview_reason=estimate["reason"],
                residual_count=estimate["residual_count"],
                routing_stats=estimate["routing_stats"],
                cpu_seconds=estimate["cpu_seconds"],
                simulated_steps=estimate["simulated_steps"],
                decision_rounds=estimate["decision_rounds"],
                **(dict(predicted_p90=p90, tail_rejected=tail_rejected) if tail_guard else {}),
            )
        )
        if batch.id == "greedy" and not valid:
            log.update(reason="incumbent_preview_failed", fallback=True)
            break
        if value is not None and not tail_rejected and value < best - 1e-12:
            best, action = value, list(batch.pairs)
            log.update(chosen=batch.id, reason="visible_rollout_improvement")
        if estimate["exhausted"]:
            log["reason"] = "decision_budget"
            break
    if log["chosen"] == "greedy":
        log["fallback"] = True
        if log["reason"] == "low_pressure":
            log["reason"] = "no_visible_improvement"
    log["visible_scales"] = list(scales) if scales else None
    return finish(action)
