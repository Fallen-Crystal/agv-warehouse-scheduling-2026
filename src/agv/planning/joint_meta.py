"""Bounded discrete ACO / random-key PSO proposals for the visible task set."""

import math
import random


def search(costs, order, owners, *, method, seed=0, budget=192):
    if method not in ("aco", "pso"):
        raise ValueError("Unknown joint metaheuristic")
    rng, n = random.Random(seed), len(order)
    cars = len(costs.obs["vehicles"])
    scales = [max(1, x) for x in costs.estimate_joint(order, owners)]
    cache, plans = {}, {}

    def evaluate(seq, assignment):
        key = tuple(seq), tuple(assignment[j] for j in seq)
        if key not in cache:
            if len(cache) >= budget:
                return math.inf
            values = costs.estimate_joint(seq, assignment)
            cache[key] = sum(w * v / s for w, v, s in zip((0.5, 0.3, 0.2), values, scales))
            plans[key] = (list(seq), dict(assignment), method)
        return cache[key]

    evaluate(order, owners)
    if method == "aco":
        # Transition pheromone and separate job/vehicle pheromone; incumbent seed.
        tau = [[1.0] * n for _ in range(n + 1)]
        own = [[1.0] * cars for _ in range(n)]
        for i, j in enumerate(order):
            tau[n if i == 0 else i - 1][i] += 1
            own[i][owners[j]] += 1
        heuristic = [
            [
                1 / max(1, costs.details(k, v["position"], costs.jobs[j])[0])
                for k, v in enumerate(costs.obs["vehicles"])
            ]
            for j in order
        ]
        for _ in range(32):
            generation = []
            for _ in range(12):
                left, indices, assignment, previous = list(range(n)), [], {}, n
                while left:
                    i = rng.choices(left, weights=[tau[previous][x] for x in left])[0]
                    k = rng.choices(
                        range(cars), weights=[own[i][k] * heuristic[i][k] for k in range(cars)]
                    )[0]
                    indices.append(i)
                    assignment[order[i]] = k
                    left.remove(i)
                    previous = i
                seq = [order[i] for i in indices]
                value = evaluate(seq, assignment)
                generation.append((value, indices, assignment))
            for matrix in (tau, own):
                for row in matrix:
                    for i in range(len(row)):
                        row[i] = max(0.02, row[i] * 0.8)
            for value, indices, assignment in sorted(generation, key=lambda x: x[0])[:3]:
                if not math.isfinite(value):
                    continue
                deposit = 1 / max(0.01, value)
                previous = n
                for i in indices:
                    tau[previous][i] += deposit
                    own[i][assignment[order[i]]] += deposit
                    previous = i
            if len(cache) >= budget:
                break
    else:

        def decode(x):
            seq = sorted(order, key=lambda j: (x[order.index(j)], j))
            assignment = {j: min(cars - 1, int(x[n + i] * cars)) for i, j in enumerate(order)}
            return seq, assignment

        positions = [[rng.random() for _ in range(2 * n)] for _ in range(12)]
        positions[0] = [(i + 0.5) / max(1, n) for i in range(n)] + [
            (owners[j] + 0.5) / cars for j in order
        ]
        velocities = [[0.0] * (2 * n) for _ in positions]
        personal = [x[:] for x in positions]
        values = [evaluate(*decode(x)) for x in positions]
        best = personal[min(range(len(values)), key=values.__getitem__)][:]
        best_value = min(values)
        for _ in range(32):
            for p, x in enumerate(positions):
                for i in range(2 * n):
                    velocity = (
                        0.7 * velocities[p][i]
                        + 1.4 * rng.random() * (personal[p][i] - x[i])
                        + 1.4 * rng.random() * (best[i] - x[i])
                    )
                    velocities[p][i] = max(-0.3, min(0.3, velocity))
                    x[i] = max(0, min(0.999999, x[i] + velocities[p][i]))
                value = evaluate(*decode(x))
                if value < values[p]:
                    values[p], personal[p] = value, x[:]
                if value < best_value:
                    best_value, best = value, x[:]
            if len(cache) >= budget:
                break
    ranked = [
        plans[k] for k in sorted(cache, key=lambda k: (cache[k], k)) if math.isfinite(cache[k])
    ]
    return ranked, dict(unique_evaluations=len(cache), budget=budget, method=method)
