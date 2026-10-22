"""Detached visible-snapshot routing feedback and stale-proposal protection."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from agv.policy.candidates import legalize
from agv.policy.forecast import ShadowState


def snapshot_key(observation):
    raw = json.dumps(
        deepcopy(observation), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DispatchProposal:
    snapshot: str
    pairs: tuple

    def resolve(self, observation):
        if snapshot_key(observation) != self.snapshot:
            raise ValueError("Stale dispatch/routing proposal")
        pairs = list(self.pairs)
        if legalize(pairs, observation) != pairs:
            raise ValueError("Illegal dispatch/routing proposal")
        return pairs


class RouteFeedback:
    def __init__(self, key, prediction):
        self.snapshot = key
        self._data = deepcopy(prediction)

    @property
    def data(self):
        return deepcopy(self._data)

    @property
    def valid_complete(self):
        return self._data["valid"] and self._data["completed"]

    def values(self, now):
        if not self.valid_complete:
            raise ValueError("Incomplete or failed routing feedback has no objective value")
        p = self._data
        return p["predicted_T"] - now, p["mean_flow_time"], p["additional_moves"]


class RoutingOracle:
    def __init__(self, observation, *, world_factory, max_previews=20, max_route_calls=1000):
        self.observation = deepcopy(observation)
        self.key = snapshot_key(observation)
        self.shadow = ShadowState.from_observation(observation, world_factory=world_factory)
        self.limit, self.route_limit = max_previews, max_route_calls
        self.previews, self.route_calls, self.expanded = 0, 0, 0

    def offer(self, pairs):
        proposal = DispatchProposal(self.key, tuple(pairs))
        proposal.resolve(self.observation)
        return proposal

    def evaluate(self, driver):
        if self.previews >= self.limit:
            raise ValueError("Routing preview budget exhausted")
        pairs = self.offer(driver(self.observation)).resolve(self.observation)
        p = self.shadow.preview(
            pairs,
            rollout_policy=driver,
            pure_empty_skips=True,
            budget=dict(max_steps=10000, max_route_calls=self.route_limit),
        )
        self.previews += 1
        self.route_calls += p["routing_stats"]["calls"]
        self.expanded += p["routing_stats"]["expanded"]
        return RouteFeedback(self.key, p)
