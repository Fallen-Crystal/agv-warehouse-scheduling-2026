"""Input-only, date-disjoint selection of complete WEPA request windows."""

import random
from collections import Counter, defaultdict

from agv.core.objectives import LinearObjective
from agv.data.wepa import build, read_source


def stratum(case):
    count = len(case["tasks"])
    inbound = sum(job["kind"] == "delivery" for job in case["tasks"]) / count
    return (
        0 if count <= 45 else 1 if count <= 60 else 2,
        0 if inbound < 0.35 else 1 if inbound <= 0.65 else 2,
    )


def partition(cases, quotas=(8, 16, 8), *, seed=20261029):
    """A source day belongs to one split, including any unselected same-day bins."""
    rng = random.Random(seed)
    grouped = defaultdict(list)
    for case in cases:
        grouped[case["source_day"]].append(case)
    by_day = list(grouped.values())
    rng.shuffle(by_day)
    for group in by_day:
        rng.shuffle(group)
    output = [[], [], []]
    # Allocate the largest partition first, keeping spare dates for smaller ones.
    for index in sorted(range(3), key=lambda i: -quotas[i]):
        counts = Counter()
        while len(output[index]) < quotas[index] and by_day:
            by_day.sort(
                key=lambda group: (min(counts[stratum(case)] for case in group), -len(group))
            )
            group = by_day.pop(0)
            group.sort(key=lambda case: counts[stratum(case)])
            take = group[: quotas[index] - len(output[index])]
            output[index].extend(take)
            counts.update(stratum(case) for case in take)
        if len(output[index]) != quotas[index]:
            raise ValueError(f"Not enough date-disjoint eligible windows for quotas={quotas}")
    days = [{case["source_day"] for case in split} for split in output]
    assert not any(days[i] & days[j] for i in range(3) for j in range(i))
    return output


def make_pool(raw_path, *, excluded_cases=(), known_days=(), seed=20261029):
    rows, stock, hashes = read_source(
        raw_path,
        expected_hashes={
            "2_orders.json": "caab14a69aa34734f3ceb04f6c595f712b7dc4a1ee65adbe92268a16a7159432",
            "3_initial_fill_lvl.json": "9f2237b8dab891d51b6925242a6691f9af826c58b0a1c09a92ad0fb8fb9ec92c",
        },
    )
    if any(a[2] > b[2] for a, b in zip(rows, rows[1:])):
        raise ValueError("Source rows must retain chronological prefix inventory")
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row[2] // 900].append((index, row))
    candidates, counters = [], Counter()
    for bucket in sorted(groups):
        entries = groups[bucket]
        kinds = Counter(row[0] for _, row in entries)
        skus = sorted({row[1] for _, row in entries})
        case_id = f"wepa-day{bucket // 96}-bin{bucket}"
        initial = {sku: stock[sku] for sku in skus}
        eligible = (
            30 <= len(entries) <= 80
            and 2 <= len(skus) <= 6
            and len(kinds) == 2
            and min(kinds.values()) >= 5
            and all(value >= 0 for value in initial.values())
            and 0 <= sum(initial.values()) <= 900
        )
        if eligible:
            counters["source_eligible"] += 1
            final = Counter(initial)
            for _, row in entries:
                final[row[1]] += 1 if row[0] == "delivery" else -1
            if min(final.values()) < 0:
                counters["negative_final_ledger"] += 1
            elif case_id in excluded_cases:
                counters["historical_window_excluded"] += 1
            else:
                case = dict(
                    case=case_id,
                    source_day=bucket // 96,
                    source_bin=bucket,
                    start_seconds=bucket * 900,
                    end_seconds=(bucket + 1) * 900,
                    close_at=900,
                    initial={str(k): value for k, value in initial.items()},
                    tasks=[
                        dict(
                            id=j,
                            source_row=i,
                            kind=r[0],
                            sku=r[1],
                            release=r[2] - bucket * 900,
                            source_time=r[2],
                            source_dock=r[3],
                            batch=r[4],
                            week=r[5],
                        )
                        for j, (i, r) in enumerate(entries)
                    ],
                )
                try:
                    build(case)
                except ValueError:
                    counters["mapping_capacity_rejected"] += 1
                else:
                    candidates.append(case)
        for _, row in entries:
            stock[row[1]] += 1 if row[0] == "delivery" else -1
    development, validation, sealed = partition(candidates, seed=seed)
    selected = development + validation + sealed
    audit = dict(
        selection_seed=seed,
        raw_rows=len(rows),
        source_sha256=hashes,
        counters=dict(counters),
        eligible_after_capacity=len(candidates),
        excluded_cases=sorted(excluded_cases),
        known_researched_dates=sorted(known_days),
        rule="Complete half-open 900-second bins;30..80 jobs;2..6 SKUs;both kinds>=5;source ledger0..900;capacity checked;date-disjoint stratified deterministic quotas8/16/8",
        algorithm_results_read=False,
        sealed_algorithms_run=False,
        windows=[
            dict(
                case=c["case"],
                source_day=c["source_day"],
                tasks=len(c["tasks"]),
                stratum=list(stratum(c)),
                previously_researched_date=c["source_day"] in known_days,
                split="development"
                if c in development
                else "validation"
                if c in validation
                else "sealed",
            )
            for c in selected
        ],
        inference="Input-selected new nonoverlapping windows; source and some dates were previously researched. Not a fresh-date generalization claim.",
    )
    return dict(
        configuration=dict(size="large", vehicles=6, layers=5),
        objective=LinearObjective().to_dict(),
        cases=selected,
        development=[c["case"] for c in development],
        validation=[c["case"] for c in validation],
        sealed=[c["case"] for c in sealed],
        methods=["gate", "gate_anchor", "gate_tail", "gate_trigger"],
        seeds=[0],
        baseline="gate",
        timeout_seconds=180,
        input_audit=audit,
    )
