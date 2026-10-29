"""Fixed physical objective with an independent stock/trajectory audit."""

from math import isclose

from agv.core.objectives import LinearObjective

__all__ = ["LinearObjective", "checked_score"]


def checked_score(model, result, objective):
    """Only complete independently validated trajectories receive a fitness."""
    from agv.evaluation.wepa import validate

    if model["vehicles"] != objective.vehicles:
        raise ValueError("Scoring fleet differs from the executed fleet")
    # Current executor moves exactly one cell per step; do not silently change speed.
    if not isclose(
        objective.speed_cells_per_second * objective.seconds_per_step,
        1.0,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ValueError("Physical speed is inconsistent with this grid executor")
    audit = validate(model, result)
    values = tuple(result[k] for k in ("T", "R", "D"))
    return dict(
        F_linear_v2=objective.score(values),
        J_equivalent_seconds=objective.equivalent_seconds(values),
        weighted_terms=dict(zip(("T", "R", "D"), objective.terms(values))),
        objective=objective.to_dict(),
        objective_sha256=objective.fingerprint,
        audit=audit,
    )
