"""Observation-only permutation search; use real SIPP rollouts for selection."""

from itertools import islice, permutations

from agv.planning.order_search import OrderCosts, exact_single
from agv.policy.bcrd import fallback
from agv.policy.candidates import legalize
from agv.policy.forecast import ShadowState, _task
from agv.warehouse.scenarios import Scenario


class ReservationPriority:
    """Search reservation priorities with fixed vehicle-task ownership.

    Every candidate replans the complete task/return trips through the same
    SIPP command gateway. This is prioritized MAPF search, not full MAPF-LNS
    and carries no CBS/EECBS approximation guarantee.
    """

    def __init__(self, *, world_factory, budget=8):
        self.factory, self.budget, self.decisions = world_factory, budget, []

    def action(self, obs, pairs):
        if len(pairs) < 2:
            return pairs
        shadow = ShadowState.from_observation(obs, world_factory=self.factory)
        candidates = [pairs, pairs[::-1]]
        candidates += list(islice(permutations(pairs), self.budget))
        seen, scales, best, chosen, logs = set(), None, 1.0, pairs, []
        for candidate in candidates:
            key = tuple(candidate)
            if key in seen or len(seen) >= self.budget:
                continue
            seen.add(key)
            prediction = shadow.preview(
                list(candidate),
                budget=dict(max_steps=2000, max_route_calls=120, max_expanded=30000),
            )
            if not prediction["valid"] or not prediction["completed"]:
                logs.append(dict(pairs=candidate, valid=False))
                if scales is None:
                    break
                continue
            values = (
                prediction["predicted_T"] - obs["time"],
                prediction["mean_flow_time"],
                prediction["additional_moves"],
            )
            if scales is None:
                scales = [max(1, x) for x in values]
            score = sum(w * v / d for w, v, d in zip((0.5, 0.3, 0.2), values, scales))
            logs.append(dict(pairs=candidate, valid=True, score=score))
            if score < best - 1e-12:
                best, chosen = score, list(candidate)
        self.decisions.append(dict(time=obs["time"], candidates=logs, selected=chosen))
        return chosen


class PriorityDriver:
    pure_empty_decisions = True

    def __init__(self, costs, order):
        self.costs, self.order = costs, list(order)

    def __call__(self, obs):
        available = {v["id"]: v for v in obs["vehicles"] if v["available"]}
        jobs = {j["id"]: j for j in obs["pending"] if j.get("dispatchable", True)}
        pairs = []
        for jid in self.order:
            if jid not in jobs or not available:
                continue
            j = jobs[jid]
            k = min(available, key=lambda k: (self.costs.trip(k, available[k]["position"], j), k))
            pairs.append((k, jid))
            del available[k]
        return legalize(pairs, obs)


class SearchPolicy:
    def __init__(self, *, world_factory, mode="ga", candidates=3):
        self.factory, self.mode, self.candidates = world_factory, mode, candidates
        self.seen, self.driver = set(), None
        self.decisions = []

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
        costs = OrderCosts(obs, s)
        if (
            self.mode == "exact"
            and len(s.homes) == 1
            and obs["time"] == 0
            and obs["order_stream_closed"]
            and len(s.tasks) <= 14
        ):
            s.order_stream_end = 0
            certificate = exact_single(s)
            self.driver = PriorityDriver(costs, certificate["order"])
            self.decisions.append(dict(time=0, method="exact", certificate=certificate))
            return self.driver(obs)
        orders = costs.search(seed=obs["time"] + sum(visible), generations=12)
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
        best, selected = 1.0, None
        logs = []
        for order in orders[: self.candidates]:
            driver = PriorityDriver(costs, order)
            prediction = shadow.preview(
                driver(obs),
                rollout_policy=driver,
                pure_empty_skips=True,
                budget=dict(max_steps=10000, max_route_calls=1000),
            )
            valid = prediction["valid"] and prediction["completed"]
            values = (
                prediction["predicted_T"] - obs["time"],
                prediction["mean_flow_time"],
                prediction["additional_moves"],
            )
            score = (
                sum(w * v / d for w, v, d in zip((0.5, 0.3, 0.2), values, scales))
                if valid
                else None
            )
            logs.append(dict(order=order, valid=valid, score=score))
            if score is not None and score < best - 1e-12:
                best, selected = score, driver
        self.decisions.append(
            dict(time=obs["time"], method="ga", candidates=logs, selected_score=best)
        )
        if selected is not None:
            self.driver = selected
            return selected(obs)
        # No adopted permutation: keep the actual greedy continuation instead
        # of accidentally using a different fixed priority after its preview.
        self.driver = None
        return safe
