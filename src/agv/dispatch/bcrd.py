"""Bounded candidate rollout dispatch, using only a detached observation.

No path, resource, service or offline objective rules are changed here. The
incumbent legal greedy batch is retained when previews fail or exhaust budget.
"""

from dataclasses import asdict
from math import isfinite
from time import perf_counter, process_time

from agv.dispatch.candidates import legalize, make_batches
from agv.dispatch.greedy import greedy_action
from agv.dispatch.optimized import matching_action
from agv.dispatch.shadow import ShadowState
from agv.simulation import Environment

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
):
    """Compare complete visible-world rollouts, with fixed per-decision scales.

    The scales are predictions from the visible greedy rollout, *not* the
    offline same-scene denominators. Zero candidate budget returns safe greedy.
    Truncated previews with residual jobs are rejected in this first version:
    an incomplete forecast cannot win by omitting a difficult order.
    """
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
    shadow = ShadowState.from_observation(observation, router_kind="sipp")
    scales, best, action = None, 1.0, safe
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
            )
        )
        if batch.id == "greedy" and not valid:
            log.update(reason="incumbent_preview_failed", fallback=True)
            break
        if value is not None and value < best - 1e-12:
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


def run(
    scenario,
    policy="bcrd",
    *,
    max_batches=4,
    depth=None,
    mode="full",
    budget=None,
    min_queue_ratio=3.0,
):
    if policy not in ("bcrd", "greedy", "matching"):
        raise ValueError("Unknown dispatch policy")
    env = Environment(scenario, router_kind="sipp")
    logs, observed = [], set()
    while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
        obs = env.observe()
        observed.update(j["id"] for j in obs["pending"])
        observed.update(v["task_id"] for v in obs["vehicles"] if v["task_id"] is not None)
        if policy == "bcrd":
            action = bcrd_action(obs, max_batches, depth, mode, budget, logs, min_queue_ratio)
        elif policy == "greedy":
            action = fallback(obs)
        else:
            action = legalize(matching_action(obs), obs) if fallback(obs) else []
        feedback = env.assign(action)
        if env.stop_if_stalled(feedback):
            break
        env.advance(observe=False)
    result = env.result()
    result["algorithm"] = dict(
        assignment=policy,
        joint=False,
        router="sipp",
        replan_calls=0,
        accepted_replans=0,
        max_batches=max_batches if policy == "bcrd" else 0,
        depth=depth,
        candidate_mode=mode,
        min_queue_ratio=min_queue_ratio,
    )
    result["observed_task_count"] = len(observed)
    meaningful = [row for row in logs if row["candidates"] or row["issued_pairs"]]
    result["dispatch_decisions"] = meaningful
    result["dispatch_stats"] = dict(
        decisions=len(meaningful),
        searched=sum(bool(row["candidates"]) for row in meaningful),
        changed=sum(row["chosen"] != "greedy" for row in meaningful),
        fallbacks=sum(row["fallback"] for row in meaningful),
        shadow_calls=sum(row["shadow_calls"] for row in meaningful),
        shadow_route_calls=sum(row["shadow_route_calls"] for row in meaningful),
        shadow_expanded=sum(row["shadow_expanded"] for row in meaningful),
        decision_cpu_seconds=sum(row["cpu_seconds"] for row in logs),
    )
    return result
