"""Recompute tiny exact lower bounds and audit hybrid paths under dense traffic."""

import argparse
import json
from fractions import Fraction
from itertools import permutations, product
from pathlib import Path

from agv.evaluation.objective import reference_context, score_result
from agv.evaluation.validation import validate
from agv.experiments.search_benchmark import fingerprints
from agv.planning.astar import Router
from agv.runner.path_research import ROUTES, run
from agv.warehouse.mixed import generate_current
from agv.warehouse.scenarios import Scenario


def exact_lower(scene):
    if len(scene.tasks) > 4 or any(j.release for j in scene.tasks):
        raise ValueError("Only tiny zero-release instances supported")
    context, router = reference_context(scene), Router(scene)
    cache = {}

    def chain_cost(k, chain):
        key = k, tuple(j.id for j in chain)
        if key not in cache:
            position, t, d, flow = scene.homes[k], 0, 0, 0
            for j in chain:
                length = min(
                    router.distance(position, p, k) + router.distance(p, j.delivery, k)
                    for p in scene.pickup_candidates(j)
                )
                t += int(length) + j.pickup_service + j.delivery_service
                d += int(length)
                flow += t
                position = j.delivery
            d += int(router.distance(position, scene.homes[k], k))
            cache[key] = t, flow, d
        return cache[key]

    best = None
    for order in permutations(scene.tasks):
        for owners in product(range(len(scene.homes)), repeat=len(order)):
            costs = [
                chain_cost(k, [j for j, o in zip(order, owners) if o == k])
                for k in range(len(scene.homes))
            ]
            T, R, D = max(c[0] for c in costs), sum(c[1] for c in costs), sum(c[2] for c in costs)
            f = (
                Fraction(T, 2 * context["time"])
                + Fraction(3 * R, 10 * len(order)) / Fraction(str(context["response"]))
                + Fraction(D, 5 * context["distance"])
            )
            if best is None or f < best:
                best = f
    return best, context


def exact_actual(scene, result, context):
    return (
        Fraction(result["makespan"], 2 * context["time"])
        + Fraction(3 * sum(r["delivery_end"] for r in result["events"]), 10 * len(scene.tasks))
        / Fraction(str(context["response"]))
        + Fraction(result["moves"], 5 * context["distance"])
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--kind", choices=("tiny", "stress"), default="tiny")
    p.add_argument("--selection", type=Path)
    a = p.parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)
    before, rows = fingerprints(), []
    if a.kind == "tiny":
        cases = []
        for path in sorted(
            Path("results/search-research-20261021/multi-exact-reference").glob("*.json")
        ):
            if path.name == "summary.json":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            s = Scenario.from_dict(data["scene"])
            lower, context = exact_lower(s)
            witness = score_result(s, data["result"])
            validate(s, witness)
            if not witness["score_valid"] or exact_actual(s, witness, context) != lower:
                raise ValueError("Stored certificate does not attain recomputed bound")
            cases.append((path.stem, s, lower, context))
        orders = ("portfolio", "assignment", "aco")
    else:
        cases = []
        for size, seed in (("medium", 8298), ("xxlarge", 8299)):
            s = generate_current(
                size=size,
                seed=seed,
                vehicles=10,
                task_count=12,
                mode="dynamic",
                arrival="burst",
                horizon=None,
                shelf_layers=8,
            )
            from dataclasses import replace

            s.tasks = [replace(j, delivery=s.stations[0]) for j in s.tasks]
            s.check()
            cases.append((f"{size}-{seed}", s, None, None))
        orders = ("greedy",)
    routes = ROUTES
    if a.selection:
        profile = json.loads(a.selection.read_text(encoding="utf-8"))
        order, route = profile["static" if a.kind == "tiny" else "dynamic"].split("__")
        orders, routes = (order,), (route,)
    for name, scene, lower, context in cases:
        for order in orders:
            for route in routes:
                row = dict(case=name, orders=order, route=route)
                try:
                    result = score_result(scene, run(scene, route=route, orders=order))
                    validate(scene, result)
                    row.update(
                        valid=result["score_valid"],
                        F=result["weighted_score"],
                        diagnostics=result["path_research"]["diagnostics"],
                    )
                    if lower is not None:
                        actual = exact_actual(scene, result, context)
                        row.update(
                            lower_F=float(lower),
                            gap_pct=float(100 * (actual / lower - 1)),
                            certified_optimal=result["score_valid"] and actual == lower,
                        )
                        if actual < lower:
                            raise ValueError("Execution below proven lower bound")
                    (out / f"{name}-{order}-{route}.json").write_text(
                        json.dumps(
                            dict(scene=scene.to_dict(), result=result, audit=row),
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except Exception as error:
                    row.update(valid=False, error=f"{type(error).__name__}: {error}")
                rows.append(row)
        print(
            json.dumps(dict(case=name, runs=len(rows), valid=sum(r["valid"] for r in rows))),
            flush=True,
        )
    if before != fingerprints():
        raise RuntimeError("Source changed during audit")
    (out / "summary.json").write_text(
        json.dumps(
            dict(
                kind=a.kind,
                source_sha256=before,
                runs=len(rows),
                valid=sum(r["valid"] for r in rows),
                rows=rows,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
