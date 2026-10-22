"""F-only acceptance of visible-order proposals; no per-metric monotonic guard."""

from agv.planning.f_search import ProposalCosts, proposal_search
from agv.policy.bcrd import fallback
from agv.policy.candidates import legalize
from agv.policy.forecast import ShadowState
from agv.warehouse.scenarios import Scenario


class BatchDriver:
    pure_empty_decisions = True

    def __init__(self, costs, order):
        self.costs, self.order = costs, list(order)

    def __call__(self, obs):
        vehicles = [v for v in obs["vehicles"] if v["available"]]
        jobs = {j["id"]: j for j in obs["pending"] if j.get("dispatchable", True)}
        chosen = [jobs[j] for j in self.order if j in jobs][: len(vehicles)]
        return legalize(self.costs.batch(vehicles, chosen), obs)


class ObjectiveSearch:
    def __init__(
        self,
        *,
        world_factory,
        method="ga",
        terms="TRD",
        matching=True,
        calibrated=True,
        budget=192,
        optimizer_seed=0,
    ):
        self.factory = world_factory
        self.method, self.terms, self.matching = method, terms, matching
        self.calibrated, self.budget, self.optimizer_seed = calibrated, budget, optimizer_seed
        self.seen, self.driver, self.decisions = set(), None, []

    def action(self, obs):
        safe = fallback(obs)
        if not safe:
            return safe
        visible = {j["id"] for j in obs["pending"]}
        new = visible - self.seen
        if self.driver is not None and not new:
            return self.driver(obs)
        self.seen |= visible
        s = Scenario.from_observation_map(obs["map"], obs["horizon"])
        costs = ProposalCosts(obs, s, matching=self.matching, calibrated=self.calibrated)
        if self.method == "matching":
            order = sorted(visible, key=lambda j: (costs.jobs[j]["release"], j))
            return BatchDriver(costs, order)(obs)
        orders, stats = proposal_search(
            costs,
            method=self.method,
            terms=self.terms,
            budget=self.budget,
            seed=obs["time"] + sum(visible) + 1000003 * self.optimizer_seed,
        )
        shadow = ShadowState.from_observation(obs, world_factory=self.factory)
        base = shadow.preview(safe)
        if not base["valid"] or not base["completed"]:
            self.decisions.append(dict(time=obs["time"], stats=stats, reason="base_incomplete"))
            return safe
        scales = [
            max(1, v)
            for v in (
                base["predicted_T"] - obs["time"],
                base["mean_flow_time"],
                base["additional_moves"],
            )
        ]
        best, chosen, logs = 1.0, None, []
        for order in orders:
            driver = BatchDriver(costs, order)
            p = shadow.preview(
                driver(obs),
                rollout_policy=driver,
                pure_empty_skips=True,
                budget=dict(max_steps=10000, max_route_calls=1000),
            )
            valid = p["valid"] and p["completed"]
            values = p["predicted_T"] - obs["time"], p["mean_flow_time"], p["additional_moves"]
            score = (
                sum(w * v / d for w, v, d in zip((0.5, 0.3, 0.2), values, scales))
                if valid
                else None
            )
            logs.append(dict(order=order, valid=valid, full_score=score, values=values))
            if score is not None and score < best - 1e-12:
                best, chosen = score, driver
        self.decisions.append(dict(time=obs["time"], stats=stats, candidates=logs, full_score=best))
        self.driver = chosen
        return chosen(obs) if chosen is not None else safe
