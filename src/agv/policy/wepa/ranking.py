"""One objective shared by proxy ranking and admissible rollout pruning."""

from math import isinf


def rank_score(values, objective):
    # Exhausted proxy budgets use +inf. Completed trajectories never do.
    if any(isinf(x) and x > 0 for x in values):
        return float("inf")
    return objective.score(values)
