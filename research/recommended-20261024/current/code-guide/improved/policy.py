"""Fixed-objective, SIPP-checked diagnostic interventions on dispatch search."""

from agv.planning.joint_orders import neighbors
from improved.forecast import rollout, snapshot
from improved.genetic import candidates
from improved.matching import matching, matching_linear
from improved.order_ga import order_candidates
from improved.profiles import PROFILES
from improved.targeted import neighborhoods
from improved.compound import compound_neighbors
from improved.hungarian import matching_hungarian
from improved.hungarian_seed import seeds as hungarian_seeds
from v2.policy import LinearPolicy
from improved.proxy import MixedCosts
from wepa.search import values


def plan_from_prediction(prediction, pending):
    records = sorted((r for r in prediction.records if r["task"] in pending),
                     key=lambda r: (r["assigned_at"], r["vehicle"], r["task"]))
    order = [r["task"] for r in records]
    owners = {r["task"]: r["vehicle"] for r in records}
    if set(order) != pending:
        raise ValueError("Incomplete anchor plan")
    return order, owners


class ResearchPolicy(LinearPolicy):
    def __init__(self, profile, seed, *, objective):
        super().__init__("soft_ga", seed, objective=objective)
        self.profile = profile
        self.settings = PROFILES[profile]

    def action(self, world):
        if self.profile == 'hungarian':
            pairs,meta=matching_hungarian(world,self.objective)
            self.logs.append(dict(time=world.time,profile=self.profile,mode='rolling_hungarian',
                matching=meta,visible_ids=sorted(world.visible),objective_sha256=self.objective.fingerprint))
            return pairs
        pending = set(world.visible) - world.assigned
        free = sum(r is None for r in world.active)
        if self.settings["gate"] and not world.closed and len(pending) <= free:
            self.plan = None
            pairs = (matching_linear(world, self.objective)
                     if self.settings.get("linear_matching") else matching(world))
            self.logs.append(dict(time=world.time, mode="immediate_batch_matching",
                                  profile=self.profile, pending=len(pending), free=free,
                                  visible_ids=sorted(world.visible),
                                  objective_sha256=self.objective.fingerprint))
            return pairs
        changed = (world.completed != self.last_completed
                   and world.time - self.last_search >= 64 and len(pending) > 1)
        if (self.plan is None or set(world.visible) - self.seen
            or (world.closed and not self.closed_seen) or changed):
            self.search(snapshot(world, terminal=self.settings.get("terminal", "home")))
            self.seen = set(world.visible)
            self.last_completed = set(world.completed)
            self.last_search, self.closed_seen = world.time, world.closed
        from wepa.search import owned_batch
        from wepa.kernel import batch
        return (owned_batch(world, *self.plan) if self.plan is not None else batch(world, "eta"))

    def search(self, view):
        settings, objective = self.settings, self.objective
        previous = self.plan
        base, usage = rollout(view)
        if base is None:
            self.plan = None
            self.logs.append(dict(time=view.time, error="anchor_incomplete", usage=usage))
            return
        pending = set(view.tasks) - view.assigned
        self.plan = plan_from_prediction(base, pending)
        first_score = best = objective.score(values(base))
        chosen, used, proxy_count = base, 1, 0
        seen = {(tuple(self.plan[0]), tuple(self.plan[1][j] for j in self.plan[0]))}
        log = []

        def consider(order, owners, kind):
            nonlocal best, chosen, used
            key = tuple(order), tuple(owners[j] for j in order)
            if key in seen or used >= settings["previews"]:
                return
            seen.add(key)
            trial, u = rollout(view, (order, owners), objective, best)
            used += 1
            score = objective.score(values(trial)) if trial is not None else None
            log.append(dict(kind=kind, score=score, usage=u))
            if score is not None and score < best - 1e-12:
                best, chosen, self.plan = score, trial, (list(order), dict(owners))

        if settings["anchor"]:
            # A comparison algorithm supplies a feasible candidate, never a denominator.
            alternate, u = rollout(view, rule="fcfs")
            used += 1
            score = objective.score(values(alternate)) if alternate is not None else None
            log.append(dict(kind="fcfs_anchor", score=score, usage=u))
            if alternate is not None:
                candidate = plan_from_prediction(alternate, pending)
                seen.add((tuple(candidate[0]), tuple(candidate[1][j] for j in candidate[0])))
                if score < best - 1e-12:
                    best, chosen, self.plan = score, alternate, candidate
        if previous is not None and pending <= set(previous[0]):
            order = [j for j in previous[0] if j in pending]
            consider(order, {j: previous[1][j] for j in order}, "incumbent")
        costs = MixedCosts(view, chosen)
        seed = self.seed * 1000003 + view.time + sum(pending)
        seed_plans,seed_meta=(hungarian_seeds(costs,*self.plan,objective)
            if settings.get('hungarian_seeds') else (None,None))
        if settings["proxy"] == 0:
            proposals=[]
        elif self.profile == "restored":
            proposals = order_candidates(costs, objective=objective, seed=seed,
                                         budget=settings["proxy"])
        else:
            proposals, _ = candidates(costs, *self.plan, objective=objective, soft=True,
                                      seed=seed, budget=settings["proxy"],
                                      generations=settings["generations"],
                                      local_seeds=settings.get("local_seeds", False),seed_plans=seed_plans)
        proxy_count += costs.evaluations
        limit = settings["previews"] - settings.get("local_previews", bool(settings["repair"]))
        for order, owners, kind in proposals:
            if used >= limit:
                break
            consider(order, owners, kind)
        if settings["repair"]:
            costs = MixedCosts(view, chosen)
            costs.allowance = settings["repair"]
            local = (compound_neighbors(costs, *self.plan, limit=settings["repair"])
                     if settings.get("compound") else
                     neighborhoods(costs, *self.plan, limit=settings["repair"])
                     if settings.get("targeted") else
                     neighbors(*self.plan, len(view.plans), seed=seed + 101,
                               limit=settings["repair"]))
            scored = []
            for order, owners, kind in local:
                estimate = costs.estimate_joint(order, owners)
                score = sum(objective.weights[i] * estimate[i] / objective.scales[i] for i in range(3))
                scored.append((score, order, owners, "repair_" + kind))
            scored.sort(key=lambda x: (x[0], tuple(x[1]), tuple(x[2][j] for j in x[1])))
            proxy_count += costs.evaluations
            for _, order, owners, kind in scored:
                if used >= settings["previews"]:
                    break
                consider(order, owners, kind)
        self.logs.append(dict(time=view.time, profile=self.profile,
                              optimizer=("hungarian_seeded_joint_ga" if self.profile=='hga' else
                                         "order_ga_repair" if self.profile == "restored" else "joint_ga"),
                              previews=used, proxy_evaluations=proxy_count,
                              visible_ids=sorted(view.visible), base_score=first_score,
                              score=best, changed=best < first_score - 1e-12,
                              anchor_usage=usage, candidates=log,
                              objective_sha256=objective.fingerprint))
        if seed_meta is not None:self.logs[-1]['hungarian_initialization']=seed_meta
