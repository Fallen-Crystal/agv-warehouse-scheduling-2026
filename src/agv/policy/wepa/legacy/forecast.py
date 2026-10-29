"""仅供复现 2026-10-24 研究包；现役 gate 不使用本历史实现。

Backend-preserving detached physical forecasts, with original safe pruning."""

from agv.planning.sipp import SafeIntervalRouter
from agv.policy.wepa.common import batch, owned_batch
from agv.policy.wepa.ranking import rank_score
from agv.policy.wepa.routing import make_router
from agv.world.wepa_snapshot import snapshot as old_snapshot


def snapshot(world):
    view = old_snapshot(world, router_factory=SafeIntervalRouter)
    view.route_kind = getattr(world, "route_kind", "sipp")
    view.route_seed = getattr(world, "route_seed", 0)
    view.router = make_router(
        view.scene,
        view.route_kind,
        view.route_seed,
        world.router.cache,
        world.router.stats,
    )
    return view


def rollout(base, plan=None, objective=None, incumbent=float("inf")):
    w = snapshot(base)
    before = w.router.stats["calls"]
    leg = w.router.leg

    class QueryBudget(Exception):
        pass

    def limited(*args, **kwargs):
        if w.router.stats["calls"] - before >= 512:
            raise QueryBudget()
        return leg(*args, **kwargs)

    w.router.leg = limited
    # The hybrid router has internal spatial/timing calls. Bound these too,
    # rather than letting a single outer call silently exceed the allowance.
    for name in ("_timed", "_spatial"):
        if hasattr(w.router, name):
            original = getattr(w.router, name)

            def inner_limited(*args, _original=original, **kwargs):
                if w.router.stats["calls"] - before >= 512:
                    raise QueryBudget()
                return _original(*args, **kwargs)

            setattr(w.router, name, inner_limited)
    limit = w.time + max(1000, len(w.tasks) * (w.scene.width + w.scene.height + 30) * 3)

    def result(value, reason):
        return value, dict(
            route_calls=w.router.stats["calls"] - before,
            reason=reason,
            backend=w.route_kind,
        )

    while w.time <= limit:
        w.publish_and_complete()
        if w.done:
            return result(w, "complete")
        if objective is not None:
            fixed = {r["task"]: r["end"] for r in w.records}
            unfinished = set(w.tasks) - set(fixed)
            lower_t = max(list(fixed.values()) + ([w.time] if unfinished else [0]))
            lower_r = sum(
                fixed.get(j, w.time) - job["release"] for j, job in w.tasks.items()
            ) / max(1, len(w.tasks))
            lower_d = w.past_moves + sum(
                w.router.distance(p[0], w.scene.homes[k], k) for k, p in enumerate(w.plans)
            )
            if rank_score((lower_t, lower_r, lower_d), objective) >= incumbent - 1e-12:
                return result(None, "bound_pruned")
        if any(r is None for r in w.active) and w.ready():
            try:
                batch(w, "eta") if plan is None else owned_batch(w, *plan)
            except QueryBudget:
                return result(None, "query_budget")
        if not w.jump_quiet():
            w.advance()
    return result(None, "incomplete")
