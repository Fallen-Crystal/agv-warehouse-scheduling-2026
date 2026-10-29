from math import ceil, isfinite
from time import process_time

from agv.core.objectives import LinearObjective
from agv.planning.sipp import SafeIntervalRouter
from agv.policy.wepa import PROFILES, Coordinator, ResearchPolicy, batch, before_action
from agv.world.wepa import World
from agv.world.wepa_snapshot import observation, snapshot


def _legacy_simple_policy(seed, objective):
    """Select the historical baseline only for the explicit simple arm."""
    from agv.policy.wepa.legacy.policy import LinearPolicy

    return LinearPolicy("soft_ga", seed, objective=objective)


def run(model, method="simple", seed=0, max_time=None, *, objective=None, latency=None):
    latency = dict(kind="none", scale=0) if latency is None else dict(latency)
    if set(latency) != {"kind", "scale"} or latency["kind"] not in ("none", "fixed", "measured"):
        raise ValueError("Latency needs kind=none/fixed/measured and scale")
    scale = latency["scale"]
    if type(scale) not in (int, float) or not isfinite(scale) or scale < 0:
        raise ValueError("Latency scale must be finite and nonnegative")
    if latency["kind"] == "fixed" and type(scale) is not int:
        raise ValueError("Fixed latency is an integer number of simulation steps")
    objective = objective or LinearObjective(vehicles=model["vehicles"])
    if objective.vehicles != model["vehicles"]:
        raise ValueError("Objective and model fleets differ")
    router = "sipp"
    w = World(model, router=SafeIntervalRouter(model["scene"]))
    w.route_kind, w.route_seed = router, seed
    w.router = SafeIntervalRouter(w.scene)
    policy = (
        _legacy_simple_policy(seed, objective)
        if method == "simple"
        else ResearchPolicy(method, seed, objective=objective)
        if method in PROFILES
        else None
    )
    if policy is None and method not in ("eta", "fcfs"):
        raise ValueError("Unknown dispatcher")
    coordinator = (
        Coordinator(objective)
        if method in PROFILES and PROFILES[method].get("coordination")
        else None
    )
    if coordinator and latency["kind"] != "none":
        raise ValueError("Delayed coordination needs a separately validated command contract")
    latency_log = []
    limit = max_time or model["close_at"] + max(3000, len(model["tasks"]) * 150)
    while w.time <= limit:
        w.publish_and_complete()
        if w.done:
            break
        if any(r is None for r in w.active) and w.ready():
            before = before_action(w) if coordinator else None
            if latency["kind"] == "none":
                pairs = policy.action(observation(w)) if policy else batch(observation(w), method)
            else:
                # Decide using t's released state; live vehicles execute while that
                # decision is pending. Every delayed trip is replanned at commit.
                started, decision_time = process_time(), w.time
                speculative = snapshot(observation(w), router_factory=SafeIntervalRouter)
                speculative.closed = w.closed
                speculative.model["close_at"] = w.time if w.closed else float("inf")
                pairs = (
                    policy.action(observation(speculative))
                    if policy
                    else batch(observation(speculative), method)
                )
                elapsed = process_time() - started
                delay = scale if latency["kind"] == "fixed" else ceil(elapsed * scale)
                while w.time < decision_time + delay and w.time < limit:
                    w.advance()
                    w.publish_and_complete()
                accepted = []
                for vehicle, task in pairs:
                    job = next((job for job in w.ready() if job["id"] == task), None)
                    if w.time > limit or w.active[vehicle] is not None or job is None:
                        continue
                    proposal = w.trip(vehicle, job)
                    if proposal is not None:
                        w.commit(vehicle, job, proposal)
                        accepted.append((vehicle, task))
                latency_log.append(
                    dict(
                        started_at=decision_time,
                        committed_at=w.time,
                        cpu_seconds=elapsed,
                        delay_steps=delay,
                        proposed=pairs,
                        accepted=accepted,
                    )
                )
                pairs = accepted
            if pairs:
                if coordinator:
                    coordinator.improve(w, pairs, before, policy.plan)
                w.decisions.append(dict(time=w.time, pairs=pairs, visible_ids=sorted(w.visible)))
        w.advance()
    flows = sorted(r["end"] - w.tasks[r["task"]]["release"] for r in w.records)
    moves = sum(a != b for p in w.history for a, b in zip(p, p[1:]))
    empty = sum(
        a != b and label != "loaded"
        for p, labels in zip(w.history, w.labels)
        for a, b, label in zip(p, p[1:], labels)
    )
    by_kind = {}
    for kind in ("delivery", "retrieval"):
        f = sorted(
            r["end"] - w.tasks[r["task"]]["release"]
            for r in w.records
            if w.tasks[r["task"]]["kind"] == kind
        )
        by_kind[kind] = dict(
            count=len(f),
            mean_flow=sum(f) / len(f) if f else 0,
            p90=f[ceil(0.9 * len(f)) - 1] if f else 0,
        )
    result = dict(
        valid=w.done,
        method=method,
        routing_backend=router,
        objective=objective.to_dict(),
        objective_sha256=objective.fingerprint,
        time=w.time,
        paths=w.history,
        labels=w.labels,
        records=w.records,
        completed=sorted(w.completed),
        decisions=w.decisions,
        T=max((r["end"] for r in w.records), default=0),
        R=sum(flows) / len(flows) if flows else 0,
        D=moves,
        empty_distance=empty,
        p90=flows[ceil(0.9 * len(flows)) - 1] if flows else 0,
        traffic_wait=sum(
            a == b and label in ("empty", "loaded")
            for p, labels in zip(w.history, w.labels)
            for a, b, label in zip(p, p[1:], labels)
        ),
        by_kind=by_kind,
        holds=w.holds,
        routing_failures=w.routing_failures,
        final_stock=sorted(w.stock),
        search_log=policy.logs if policy else [],
        routing_stats=dict(w.router.stats),
        routing_diagnostics=getattr(w.router, "diagnostics", {}),
        coordination_log=coordinator.logs if coordinator else [],
    )
    if latency["kind"] != "none":
        result["decision_latency"] = dict(model=latency, events=latency_log)
    return result
