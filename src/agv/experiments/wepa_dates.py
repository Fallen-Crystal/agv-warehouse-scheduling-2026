"""Date-level paired inference; repeated windows do not increase the date count."""

import math
import random
import statistics
from collections import defaultdict

from agv.data.wepa.windows import original_filter_subset


def _summary(pairs, cases, *, resamples, seed):
    grouped = defaultdict(list)
    for pair in pairs:
        grouped[cases[pair["case"]]["source_day"]].append(pair)
    days = [
        dict(
            source_day=day,
            windows=len(rows),
            gain_percent=statistics.mean(row["gain_percent"] for row in rows),
            deltas={
                key: statistics.mean(row["deltas"][key] for row in rows)
                for key in rows[0]["deltas"]
            },
        )
        for day, rows in sorted(grouped.items())
    ]
    gains = [day["gain_percent"] for day in days]
    positive = sum(g > 1e-10 for g in gains)
    negative = sum(g < -1e-10 for g in gains)
    n = positive + negative
    pvalue = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(positive, negative) + 1)) / 2**n)
    interval = None
    if len(gains) >= 2:
        rng = random.Random(seed)
        samples = sorted(
            statistics.mean(rng.choices(gains, k=len(gains))) for _ in range(resamples)
        )
        interval = [samples[int(resamples * 0.025)], samples[int(resamples * 0.975)]]
    return dict(
        dates=days,
        comparable_dates=len(days),
        comparable_windows=len(pairs),
        mean_gain_percent=statistics.mean(gains) if gains else None,
        median_gain_percent=statistics.median(gains) if gains else None,
        bootstrap95=interval,
        improved=positive,
        worsened=negative,
        tied=len(gains) - n,
        sign_test_two_sided_p=pvalue,
        mean_deltas={
            key: statistics.mean(day["deltas"][key] for day in days) for key in days[0]["deltas"]
        }
        if days
        else {},
    )


def summarize_dates(pairs, cases, *, resamples=4000, seed=20261029):
    """Summarize complete, already-audited pairs, weighting each date equally."""
    declared = {case["case"]: case for case in cases}
    if (
        len(declared) != len(cases)
        or len(pairs) != len(declared)
        or {pair["case"] for pair in pairs} != set(declared)
    ):
        raise ValueError("Need one complete paired result per declared window")
    if type(resamples) is not int or resamples < 100:
        raise ValueError("Need at least 100 bootstrap resamples")
    delta_keys = set(pairs[0]["deltas"]) if pairs else set()
    if any(
        set(pair["deltas"]) != delta_keys
        or not all(
            type(value) in (int, float) and math.isfinite(value)
            for value in (pair["gain_percent"], *pair["deltas"].values())
        )
        for pair in pairs
    ):
        raise ValueError("Paired metrics must be finite and use the same delta fields")
    original = [pair for pair in pairs if original_filter_subset(declared[pair["case"]])]
    return dict(
        all=_summary(pairs, declared, resamples=resamples, seed=seed),
        original_filter_subset=_summary(original, declared, resamples=resamples, seed=seed),
        inference="Mean window improvement within each date, then equal date weights; percentile bootstrap over dates; exact two-sided binomial sign test excludes ties. Reused dates are not fresh holdout.",
    )
