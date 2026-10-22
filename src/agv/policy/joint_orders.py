"""Optional joint visible-order search with real SIPP feedback before commitment."""

import random

from agv.planning.joint_meta import search
from agv.planning.joint_orders import JointCosts, neighbors
from agv.policy.bcrd import fallback
from agv.policy.candidates import legalize
from agv.policy.f_portfolio import PortfolioSearch
from agv.policy.routing_contract import DispatchProposal, RoutingOracle, snapshot_key
from agv.warehouse.scenarios import Scenario


class OwnedDriver:
    pure_empty_decisions = True

    def __init__(self, order, owners, priority=None):
        self.order, self.owners = list(order), dict(owners)
        self.priority = priority

    def __call__(self, obs):
        available = {v["id"] for v in obs["vehicles"] if v["available"]}
        pending = {j["id"] for j in obs["pending"] if j.get("dispatchable", True)}
        pairs = []
        for j in self.order:
            k = self.owners[j]
            if j in pending and k in available:
                pairs.append((k, j))
                available.remove(k)
        pairs = legalize(pairs, obs)
        if self.priority is not None:
            pairs.sort(key=lambda p: self.priority.index(p[0]))
        return pairs


class _Priority:
    pure_empty_decisions = True

    def __init__(self, driver, priority):
        self.driver, self.priority = driver, priority

    def __call__(self, obs):
        return sorted(self.driver(obs), key=lambda p: self.priority.index(p[0]))


class _Fallback:
    pure_empty_decisions = True

    def __call__(self, obs):
        return fallback(obs)


class JointOrderPolicy:
    def __init__(self, *, world_factory, mode="combined", candidate_budget=8, optimizer_seed=0):
        if mode not in ("assignment", "priority", "combined", "random", "aco", "pso"):
            raise ValueError("Unknown joint search mode")
        if candidate_budget < 1:
            raise ValueError("Positive candidate budget required")
        self.factory, self.mode = world_factory, mode
        self.budget, self.seed = candidate_budget, optimizer_seed
        self.seen, self.driver, self.decisions, self.commit_feedback = set(), None, [], []
        self.expected = {}

    def action(self, obs):
        if not fallback(obs):
            return []
        visible = {j["id"] for j in obs["pending"]}
        if self.driver is None or visible - self.seen:
            self._search(obs)
            self.seen |= visible
        # Stamping an action needs no reconstructed shadow or routing oracle.
        return DispatchProposal(snapshot_key(obs), tuple(self.driver(obs))).resolve(obs)

    def _search(self, obs):
        anchor = PortfolioSearch(world_factory=self.factory, optimizer_seed=self.seed)
        anchor.action(obs)
        incumbent = anchor.driver or _Fallback()
        oracle = RoutingOracle(obs, world_factory=self.factory, max_previews=self.budget + 1)
        base = oracle.evaluate(incumbent)
        self.driver = incumbent
        log = dict(
            time=obs["time"], mode=self.mode, baseline_decisions=anchor.decisions, candidates=[]
        )
        if not base.valid_complete:
            log["reason"] = "anchor_incomplete"
            self.decisions.append(log)
            return
        pending = {j["id"] for j in obs["pending"]}
        records = sorted(
            (r for r in base.data["assignments"] if r["task_id"] in pending),
            key=lambda r: (r["assigned_at"], r["vehicle"], r["task_id"]),
        )
        order = [r["task_id"] for r in records]
        owners = {r["task_id"]: r["vehicle"] for r in records}
        if set(order) != pending:
            raise ValueError("Complete anchor lacks pending assignments")
        costs = JointCosts(obs, Scenario.from_observation_map(obs["map"], obs["horizon"]))
        seed = self.seed * 1000003 + obs["time"] + sum(order)
        rng = random.Random(seed)
        cars = list(range(len(obs["vehicles"])))
        proposals, stats = [], dict(unique_evaluations=0, budget=192)
        if self.mode != "priority":
            if self.mode in ("aco", "pso"):
                plans, stats = search(costs, order, owners, method=self.mode, seed=seed, budget=192)
            else:
                plans = neighbors(order, owners, len(cars), seed=seed, limit=192)
                scales = [max(1, x) for x in costs.estimate_joint(order, owners)]
                ranked = [
                    (
                        sum(
                            w * v / s
                            for w, v, s in zip((0.5, 0.3, 0.2), costs.estimate_joint(o, a), scales)
                        ),
                        o,
                        a,
                        k,
                    )
                    for o, a, k in plans
                ]
                stats["unique_evaluations"] = len(ranked)
                if self.mode == "random":
                    rng.shuffle(ranked)
                else:
                    ranked.sort(key=lambda x: (x[0], tuple(x[1]), tuple(x[2][j] for j in x[1])))
                plans = [(o, a, k) for _, o, a, k in ranked]
            quota = self.budget if self.mode != "combined" else max(1, self.budget - 3)
            proposals.extend((kind, OwnedDriver(o, a)) for o, a, kind in plans[:quota])
        if self.mode in ("priority", "combined"):
            priorities = [list(reversed(cars))] + [cars[i:] + cars[:i] for i in range(1, len(cars))]
            rng.shuffle(priorities)
            for p in priorities:
                proposals.append(("reservation_priority", _Priority(incumbent, p)))
        scales = [max(1, x) for x in base.values(obs["time"])]
        best, chosen = 1.0, base
        for kind, driver in proposals[: self.budget]:
            p = oracle.evaluate(driver)
            value = (
                sum(w * v / s for w, v, s in zip((0.5, 0.3, 0.2), p.values(obs["time"]), scales))
                if p.valid_complete
                else None
            )
            log["candidates"].append(dict(kind=kind, valid=p.valid_complete, score=value))
            if value is not None and value < best - 1e-12:
                best, self.driver, chosen = value, driver, p
        self.expected = {r["task_id"]: r for r in chosen.data["assignments"]}
        log.update(
            score=best,
            stats=stats,
            previews=oracle.previews,
            route_calls=oracle.route_calls,
            expanded=oracle.expanded,
        )
        self.decisions.append(log)

    def on_assignment(self, before, feedback, after):
        if not feedback:
            return
        rejected, mismatch = False, False
        for r in feedback:
            rejected |= not r["accepted"]
            expected = self.expected.get(r["task_id"])
            if r["accepted"] and expected:
                mismatch |= (r["vehicle"], r["planned_delivery_end"], tuple(r["pickup_point"])) != (
                    expected["vehicle"],
                    expected["delivery_end"],
                    tuple(expected["pickup_point"]),
                )
        self.commit_feedback.append(
            dict(
                time=before["time"],
                post_time=after["time"],
                rejected=rejected,
                prediction_mismatch=mismatch,
                accepted=sum(r["accepted"] for r in feedback),
                available_after=[v["id"] for v in after["vehicles"] if v["available"]],
            )
        )
        if rejected or mismatch:
            self.driver = None
