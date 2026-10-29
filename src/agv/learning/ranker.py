"""Small transparent ridge regressor for candidate search-budget allocation.

It predicts candidate value from current visible plans, never future orders.
Safety is always decided by the independent route/service validator.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from agv.core.features import features as features

FEATURES = (
    "vehicle_count",
    "stationary_steps",
    "max_stationary_steps",
    "spatial_overlap",
    "remaining_steps",
    "first_stationary_steps",
    "first_remaining",
    "frozen_services",
)


@dataclass(frozen=True)
class CandidateRanker:
    means: tuple
    scales: tuple
    weights: tuple
    intercept: float

    def predict(self, values):
        if len(values) != len(FEATURES):
            raise ValueError("Feature shape mismatch")
        return self.intercept + sum(
            w * (x - m) / s for x, m, s, w in zip(values, self.means, self.scales, self.weights)
        )

    def to_dict(self):
        return dict(
            schema="agv-candidate-ranker-v1",
            features=FEATURES,
            means=self.means,
            scales=self.scales,
            weights=self.weights,
            intercept=self.intercept,
        )

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            data.get("schema") != "agv-candidate-ranker-v1"
            or tuple(data.get("features", ())) != FEATURES
        ):
            raise ValueError("Unsupported candidate model schema/features")
        columns = [tuple(data[key]) for key in ("means", "scales", "weights")]
        if any(len(c) != len(FEATURES) for c in columns):
            raise ValueError("Model shape mismatch")
        if not all(type(v) in (int, float) and math.isfinite(v) for c in columns for v in c):
            raise ValueError("Nonfinite/non-numeric model parameter")
        if (
            any(s <= 0 for s in columns[1])
            or type(data.get("intercept")) not in (int, float)
            or not math.isfinite(data["intercept"])
        ):
            raise ValueError("Invalid model scale/intercept")
        return cls(*columns, data["intercept"])


def fit(samples, regularization=0.1, steps=1000):
    if not samples:
        raise ValueError("No training observations")
    n = len(samples)
    dim = len(FEATURES)
    means = [sum(s["features"][j] for s in samples) / n for j in range(dim)]
    scales = [
        max(1e-8, (sum((s["features"][j] - means[j]) ** 2 for s in samples) / n) ** 0.5)
        for j in range(dim)
    ]
    x = [[(v - m) / scale for v, m, scale in zip(s["features"], means, scales)] for s in samples]
    y = [s["target"] for s in samples]
    intercept = sum(y) / n
    weights = [0.0] * dim
    # Deterministic batch gradient descent; no ML framework required.
    for _ in range(steps):
        gradient = [0.0] * dim
        for row, target in zip(x, y):
            error = intercept + sum(a * b for a, b in zip(row, weights)) - target
            for j in range(dim):
                gradient[j] += error * row[j] / n
        weights = [w - 0.03 * (g + regularization * w) for w, g in zip(weights, gradient)]
    return CandidateRanker(tuple(means), tuple(scales), tuple(weights), intercept)
