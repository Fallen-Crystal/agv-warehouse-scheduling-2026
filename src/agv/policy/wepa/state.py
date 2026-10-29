"""Shared rolling-policy bookkeeping without a historical search implementation."""


class RollingPolicyState:
    def __init__(self, method="soft_ga", seed=0, *, objective):
        if method not in ("simple_ga", "soft_ga"):
            raise ValueError("Unknown simple policy")
        self.objective = objective
        self.method, self.seed = method, seed
        self.plan, self.seen, self.logs = None, set(), []
        self.last_search, self.last_completed, self.closed_seen = -10000, set(), False
