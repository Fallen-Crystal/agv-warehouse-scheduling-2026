"""Exhaustive small assignment/order relaxation, with full-model certificates.

The relaxed optimum ignores collisions and cross-vehicle shelf locking. A
fully independently validated witness attaining it certifies the original
problem optimum, because the feasible set is a subset of the relaxation.
Non-attainment is reported as an unresolved gap, NEVER as an exact solution.
"""

import json
from fractions import Fraction
from itertools import permutations, product
from pathlib import Path

from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.planning.astar import Router
from agv.registry import SolverSpec
from agv.runner.run import run
from agv.warehouse.mixed import generate_current

out = Path("runs/multi-exact-reference")
out.mkdir(exist_ok=True)
rows = []
for size in ("medium", "large", "xlarge", "xxlarge"):
    for seed in (62, 63):
        s = generate_current(
            size=size,
            seed=seed,
            vehicles=2,
            task_count=3,
            mode="static",
            shelf_layers=8,
            horizon=None,
        )
        context, router = reference_context(s), Router(s)
        best, best_chains, explored = None, None, 0
        cache = {}

        def route(vehicle, chain):
            key = vehicle, tuple(j.id for j in chain)
            if key in cache:
                return cache[key]
            position, t, d, cs = s.homes[vehicle], 0, 0, 0
            for job in chain:
                length = min(
                    router.distance(position, p, vehicle)
                    + router.distance(p, job.delivery, vehicle)
                    for p in s.pickup_candidates(job)
                )
                t += int(length) + job.pickup_service + job.delivery_service
                d += int(length)
                cs += t
                position = job.delivery
            d += int(router.distance(position, s.homes[vehicle], vehicle))
            cache[key] = t, cs, d
            return cache[key]

        # Every feasible allocation/order maps to at least one enumerated
        # pair of chains. Duplicates only increase work, not the lower bound.
        for order in permutations(s.tasks):
            for choices in product(range(2), repeat=len(s.tasks)):
                chains = [
                    [j for j, k in zip(order, choices) if k == vehicle] for vehicle in range(2)
                ]
                costs = [route(k, c) for k, c in enumerate(chains)]
                T, sumC, D = (
                    max(c[0] for c in costs),
                    sum(c[1] for c in costs),
                    sum(c[2] for c in costs),
                )
                score = (
                    Fraction(T, 2 * context["time"])
                    + Fraction(3 * sumC, 10 * len(s.tasks)) / Fraction(str(context["response"]))
                    + Fraction(D, 5 * context["distance"])
                )
                explored += 1
                if best is None or score < best:
                    best = score
                    best_chains = [[j.id for j in c] for c in chains]

        def action(obs):
            legal = {j["id"] for j in obs["pending"] if j["dispatchable"]}
            assigned = {r["task_id"] for r in obs["completed"]}
            assigned |= {v["task_id"] for v in obs["vehicles"] if v["task_id"] is not None}
            pairs = []
            for v in obs["vehicles"]:
                if not v["available"]:
                    continue
                remaining = [j for j in best_chains[v["id"]] if j not in assigned]
                if remaining and remaining[0] in legal:
                    pairs.append((v["id"], remaining[0]))
            # One shared face per batch remains enforced by the real executor.
            jobs = {j["id"]: j for j in obs["pending"]}
            faces, selected = set(), []
            for v, j in pairs:
                face = tuple(jobs[j]["shelf"])
                if face not in faces:
                    selected.append((v, j))
                    faces.add(face)
            return selected

        result = score_result(s, run(SolverSpec(router="sipp"), s, action=action))
        validate(s, result)
        actual_sumC = sum(e["delivery_end"] for e in result["events"])
        actual_exact = (
            Fraction(result["makespan"], 2 * context["time"])
            + Fraction(3 * actual_sumC, 10 * len(s.tasks)) / Fraction(str(context["response"]))
            + Fraction(result["moves"], 5 * context["distance"])
        )
        tight = result["score_valid"] and actual_exact == best
        row = dict(
            size=size,
            seed=seed,
            vehicles=2,
            orders=3,
            enumerations=explored,
            relaxed_lower_F=float(best),
            feasible_F=result["weighted_score"],
            certified_optimal=tight,
            gap_pct=float(100 * (actual_exact / best - 1)),
            chains=best_chains,
            lower_fraction=[best.numerator, best.denominator],
            actual_fraction=[actual_exact.numerator, actual_exact.denominator],
        )
        rows.append(row)
        (out / f"{size}-{seed}.json").write_text(
            json.dumps(dict(scene=s.to_dict(), result=result, certificate=row)), encoding="utf-8"
        )
        print(json.dumps(row), flush=True)
(out / "summary.json").write_text(
    json.dumps(dict(rows=rows, certified=sum(r["certified_optimal"] for r in rows)), indent=2),
    encoding="utf-8",
)
