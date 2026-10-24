"""Backend-preserving detached physical forecasts, with original safe pruning."""

from wepa.search import snapshot as old_snapshot, owned_batch
from v2.ranking import rank_score
from wepa.kernel import batch
from simple.routing import make_router


def snapshot(world, *, terminal=None):
    view = old_snapshot(world)
    # Carry public closure status across repeated sanitization. Never retain the
    # real close_at, unpublished jobs, or their count in a policy observation.
    view.observed_closed = getattr(world, "observed_closed", world.closed)
    view.forecast_terminal = terminal or getattr(world, "forecast_terminal", "home")
    if view.forecast_terminal == "standby" and not view.observed_closed:
        view.model["close_at"] = float("inf")
        view.closed = False
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


def rollout(base, plan=None, objective=None, incumbent=float("inf"), *, rule="eta"):
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
            terminal=w.forecast_terminal,
            observed_closed=w.observed_closed,
        )

    while w.time <= limit:
        w.publish_and_complete()
        if w.done:
            return result(w, "complete")
        if not w.closed and len(w.completed) == len(w.tasks):
            # The actual one-tick executor must reach a fixed point: all idle
            # cars hold safely forever under the same relative reservations.
            # Merely being on an ordinary cell is insufficient if a peer suffix
            # will force the car to move. Keep every fallback reservation intact.
            previous = [list(p) for p in w.plans]
            w.advance()
            if w.plans == previous and all(
                w.ordinary(p[0]) or p[0] == w.scene.homes[k]
                for k, p in enumerate(w.plans)
            ):
                return result(w, "complete_standby")
            continue
        if objective is not None:
            fixed = {r["task"]: r["end"] for r in w.records}
            unfinished = set(w.tasks) - set(fixed)
            lower_t = max(list(fixed.values()) + ([w.time] if unfinished else [0]))
            lower_r = sum(
                fixed.get(j, w.time) - job["release"] for j, job in w.tasks.items()
            ) / max(1, len(w.tasks))
            lower_d = w.past_moves + (sum(
                w.router.distance(p[0], w.scene.homes[k], k)
                for k, p in enumerate(w.plans)
            ) if w.closed else 0)
            if rank_score((lower_t, lower_r, lower_d), objective) >= incumbent - 1e-12:
                return result(None, "bound_pruned")
        if any(r is None for r in w.active) and w.ready():
            try:
                batch(w, rule) if plan is None else owned_batch(w, *plan)
            except QueryBudget:
                return result(None, "query_budget")
        if not w.jump_quiet():
            w.advance()
    return result(None, "incomplete")
