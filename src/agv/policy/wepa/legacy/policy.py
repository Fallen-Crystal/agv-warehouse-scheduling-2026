"""仅供复现 2026-10-24 研究包；现役 gate 不使用本历史实现。"""

from agv.policy.wepa.common import batch, owned_batch, values
from agv.policy.wepa.legacy.forecast import rollout, snapshot
from agv.policy.wepa.legacy.genetic import candidates
from agv.policy.wepa.legacy.proxy import MixedCosts
from agv.policy.wepa.ranking import rank_score
from agv.policy.wepa.state import RollingPolicyState


class LinearPolicy(RollingPolicyState):
    def action(self, world):
        pending = set(world.visible) - world.assigned
        changed = (
            world.completed != self.last_completed
            and world.time - self.last_search >= 64
            and len(pending) > 1
        )
        if (
            self.plan is None
            or set(world.visible) - self.seen
            or (world.closed and not self.closed_seen)
            or changed
        ):
            self.search(snapshot(world))
            self.seen = set(world.visible)
            self.last_completed = set(world.completed)
            self.last_search, self.closed_seen = world.time, world.closed
        return owned_batch(world, *self.plan) if self.plan is not None else batch(world, "eta")

    def search(self, view):
        old = self.plan
        baseline, usage = rollout(view)
        if baseline is None:
            self.plan = None
            self.logs.append(
                dict(
                    time=view.time,
                    error="visible_anchor_incomplete",
                    visible_ids=sorted(view.visible),
                    usage=usage,
                )
            )
            return
        pending = set(view.tasks) - view.assigned
        records = sorted(
            (r for r in baseline.records if r["task"] in pending),
            key=lambda r: (r["assigned_at"], r["vehicle"], r["task"]),
        )
        order = [r["task"] for r in records]
        owners = {r["task"]: r["vehicle"] for r in records}
        assert set(order) == pending
        self.plan = order, owners
        objective = self.objective
        base_score = objective.score(values(baseline))
        best, used = base_score, 1
        previews, seen = [], {(tuple(order), tuple(owners[j] for j in order))}
        if old is not None and pending <= set(old[0]):
            o = [j for j in old[0] if j in pending]
            a = {j: old[1][j] for j in o}
            key = tuple(o), tuple(a[j] for j in o)
            if key not in seen:
                seen.add(key)
                trial, u = rollout(view, (o, a), objective, best)
                used += 1
                score = rank_score(values(trial), objective) if trial is not None else None
                previews.append(dict(kind="incumbent", score=score, usage=u))
                if score is not None and score < best - 1e-12:
                    best, self.plan = score, (o, a)
        costs = MixedCosts(view, baseline)
        plans, activity = candidates(
            costs,
            order,
            owners,
            objective=objective,
            soft=self.method == "soft_ga",
            seed=self.seed * 1000003 + view.time + sum(order),
        )
        for o, a, kind in plans:
            if used >= 3:
                break
            key = tuple(o), tuple(a[j] for j in o)
            if key in seen:
                continue
            seen.add(key)
            trial, u = rollout(view, (o, a), objective, best)
            used += 1
            score = rank_score(values(trial), objective) if trial is not None else None
            previews.append(dict(kind=kind, score=score, usage=u))
            if score is not None and score < best - 1e-12:
                best, self.plan = score, (o, a)
        self.logs.append(
            dict(
                time=view.time,
                optimizer="ga",
                method=self.method,
                backend=view.route_kind,
                previews=used,
                proxy_evaluations=activity["proxy_evaluations"],
                visible_ids=sorted(view.visible),
                score=best,
                base_score=base_score,
                objective_sha256=objective.fingerprint,
                fixed_scales=list(objective.scales),
                changed=best < base_score - 1e-12,
                anchor_usage=usage,
                candidates=previews,
                soft_region=self.method == "soft_ga",
                regions=2,
                global_owner_proposal_probability=0.25 if self.method == "soft_ga" else 1.0,
            )
        )
