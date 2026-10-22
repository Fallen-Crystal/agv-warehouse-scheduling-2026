"""Diverse whole-visible-schedule candidates, anchored by the existing v1 search."""

from agv.planning.f_search import ProposalCosts, proposal_search
from agv.planning.order_search import OrderCosts
from agv.policy.bcrd import fallback
from agv.policy.f_search import BatchDriver
from agv.policy.forecast import ShadowState, _task
from agv.policy.research_search import PriorityDriver
from agv.warehouse.scenarios import Scenario


class PortfolioSearch:
    def __init__(self, *, world_factory, optimizer_seed=0):
        self.factory, self.optimizer_seed = world_factory, optimizer_seed
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
        s.tasks = [_task(j) for j in obs["pending"]]
        legacy = OrderCosts(obs, s)
        proposals = [
            ("v1", order, PriorityDriver(legacy, order))
            for order in legacy.search(seed=obs["time"] + sum(visible), generations=12)[:3]
        ]
        costs = ProposalCosts(obs, Scenario.from_observation_map(obs["map"], obs["horizon"]))
        for terms in ("TR", "RD"):
            orders, _ = proposal_search(
                costs,
                terms=terms,
                budget=192,
                seed=obs["time"] + sum(visible) + 1000003 * self.optimizer_seed,
            )
            proposals.extend((terms, order, BatchDriver(costs, order)) for order in orders)
        shadow = ShadowState.from_observation(obs, world_factory=self.factory)
        base = shadow.preview(safe)
        if not base["valid"] or not base["completed"]:
            return safe
        scales = [
            max(1, v)
            for v in (
                base["predicted_T"] - obs["time"],
                base["mean_flow_time"],
                base["additional_moves"],
            )
        ]
        chosen, best, logs, used = None, 1.0, [], set()
        for group, order, driver in proposals:
            key = group == "v1", tuple(order)
            if key in used:
                continue
            used.add(key)
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
            logs.append(
                dict(group=group, order=order, valid=valid, full_score=score, values=values)
            )
            if score is not None and score < best - 1e-12:
                chosen, best = driver, score
        self.driver = chosen
        self.decisions.append(
            dict(
                time=obs["time"],
                full_score=best,
                candidates=logs,
                selected_group=next((p[0] for p in proposals if p[2] is chosen), "fallback"),
                budget_note="v1 plus two 192-cap proposal searches, at most nine candidate rollouts; not equal budget to v1",
            )
        )
        return chosen(obs) if chosen is not None else safe
