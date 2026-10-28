"""Linear fitness from physical metrics only; no benchmark-run denominators."""

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isclose, isfinite


@dataclass(frozen=True)
class LinearObjective:
    version: str = "linear-physical-v2-20261024"
    horizon_seconds: float = 900.0
    vehicles: int = 6
    speed_cells_per_second: float = 1.0
    seconds_per_step: float = 1.0
    weights: tuple = (0.5, 0.3, 0.2)

    def __post_init__(self):
        if self.version != "linear-physical-v2-20261024":
            raise ValueError("Unknown objective version")
        if type(self.vehicles) is not int or self.vehicles <= 0:
            raise ValueError("Fleet size must be a positive integer")
        for x in (self.horizon_seconds, self.speed_cells_per_second, self.seconds_per_step):
            if isinstance(x, bool) or not isfinite(x) or x <= 0:
                raise ValueError("Physical scales must be positive and finite")
        if len(self.weights) != 3 or any(
            isinstance(x, bool) or not isfinite(x) or x <= 0 for x in self.weights
        ) or not isclose(sum(self.weights), 1.0, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Three positive weights must sum to one")

    @property
    def scales(self):
        """Denominators for T/R in native steps and D in native cells."""
        return (
            self.horizon_seconds / self.seconds_per_step,
            self.horizon_seconds / self.seconds_per_step,
            self.vehicles * self.speed_cells_per_second * self.horizon_seconds,
        )

    def terms(self, values):
        if len(values) != 3 or any(
            isinstance(x, bool) or not isfinite(x) or x < 0 for x in values
        ):
            raise ValueError("T/R/D must be finite nonnegative physical metrics")
        return tuple(w * x / s for w, x, s in zip(self.weights, values, self.scales))

    def score(self, values):
        return sum(self.terms(values))

    def equivalent_seconds(self, values):
        return self.horizon_seconds * self.score(values)

    def to_dict(self):
        data = asdict(self)
        data["weights"] = list(self.weights)
        return data

    @property
    def fingerprint(self):
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def checked_score(model, result, objective):
    """Only complete independently validated trajectories receive a fitness."""
    from wepa.check import validate

    if model["vehicles"] != objective.vehicles:
        raise ValueError("Scoring fleet differs from the executed fleet")
    # Current executor moves exactly one cell per step; do not silently change speed.
    if not isclose(
        objective.speed_cells_per_second * objective.seconds_per_step, 1.0,
        rel_tol=0, abs_tol=1e-12,
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
