from math import ceil
from wepa.kernel import World, batch
from simple.routing import make_router
from v2.policy import LinearPolicy
from improved.policy import ResearchPolicy
from improved.profiles import PROFILES
from objective import LinearObjective
from improved.coordination import Coordinator, before_action


def run(model, method="simple", seed=0, max_time=None, *, objective=None):
    objective = objective or LinearObjective(vehicles=model["vehicles"])
    if objective.vehicles != model["vehicles"]:
        raise ValueError("Objective and model fleets differ")
    router = "sipp"
    w = World(model)
    w.route_kind, w.route_seed = router, seed
    w.router = make_router(w.scene, router, seed)
    policy = (LinearPolicy("soft_ga", seed, objective=objective) if method == "simple" else
              ResearchPolicy(method, seed, objective=objective) if method in PROFILES else None)
    if policy is None and method not in ("eta", "fcfs"):
        raise ValueError("Unknown dispatcher")
    coordinator = (Coordinator(objective) if method in PROFILES and
                   PROFILES[method].get("coordination") else None)
    limit = max_time or model["close_at"] + max(3000, len(model["tasks"]) * 150)
    while w.time <= limit:
        w.publish_and_complete()
        if w.done:
            break
        if any(r is None for r in w.active) and w.ready():
            before = before_action(w) if coordinator else None
            pairs = policy.action(w) if policy else batch(w, method)
            if pairs:
                if coordinator:
                    coordinator.improve(w,pairs,before,policy.plan)
                w.decisions.append(
                    dict(time=w.time, pairs=pairs, visible_ids=sorted(w.visible))
                )
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
    return dict(
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
