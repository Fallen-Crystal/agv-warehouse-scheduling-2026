"""One joint GA: sequence plus owner genes; no separate matching or repair."""

import random
from math import isfinite
from v2.ranking import rank_score


def candidates(costs, order, owners, *, objective, soft=False, seed=0, budget=96, generations=8, local_seeds=False, seed_plans=None):
    rng = random.Random(seed)
    costs.allowance = budget
    cars = len(costs.obs["vehicles"])
    pools = {}
    for j in order:
        job = costs.jobs[j]
        options = []
        target_region = costs.slots[j]["shelf"][1] >= costs.world.scene.height / 2
        local = []
        for k, v in enumerate(costs.obs["vehicles"]):
            active = costs.world.active[k]
            position = active["drop"] if active else v["position"]
            available = (
                max(costs.world.time, active["end"]) if active else costs.world.time
            )
            distance = costs.details(k, position, job)[0]
            options.append((available + distance, k))
            if (position[1] >= costs.world.scene.height / 2) == target_region:
                local.append(k)
        pools[j] = sorted(set(local) | {k for _, k in sorted(options)[:3]})
    evaluated = {}

    def evaluate(item):
        o, a = item
        key = tuple(o), tuple(a[j] for j in o)
        if key not in evaluated:
            if len(evaluated) >= budget:
                return float("inf")
            values = costs.estimate_joint(o, a)
            score = rank_score(values, objective)
            evaluated[key] = (score, (list(o), dict(a), "ga"))
        return evaluated[key][0]

    def random_owner(j):
        choices = pools[j] if soft and rng.random() < 0.75 else list(range(cars))
        return rng.choice(choices)

    population = [(list(order), dict(owners))]
    for index in range(11):
        o = list(order)
        a = dict(owners)
        if local_seeds and index < 8:
            # Most seeds retain a feasible schedule's structure instead of
            # simultaneously randomizing every task's vehicle and order.
            if index < 4 and o:
                j = rng.choice(o)
                alternatives = [k for k in range(cars) if k != a[j]]
                if alternatives:
                    a[j] = rng.choice(alternatives)
            elif len(o) > 1:
                i, j = rng.sample(range(len(o)), 2)
                if index < 6:
                    o[i], o[j] = o[j], o[i]
                else:
                    o.insert(j, o.pop(i))
        else:
            rng.shuffle(o)
            a = {j: random_owner(j) for j in o}
        population.append((o, a))
    for index,(o,a,kind) in enumerate((seed_plans or [])[:2]):
        if len(o)!=len(order) or set(o)!=set(order) or set(a)!=set(order):
            raise ValueError('Incomplete Hungarian seed')
        population[index+1]=(list(o),dict(a))
    for _ in range(generations):
        population.sort(
            key=lambda x: (evaluate(x), tuple(x[0]), tuple(x[1][j] for j in x[0]))
        )
        next_population = [(list(o), dict(a)) for o, a in population[:2]]
        while len(next_population) < 12:
            left = min(rng.sample(population, min(3, len(population))), key=evaluate)
            right = min(rng.sample(population, min(3, len(population))), key=evaluate)
            n = len(order)
            if n > 1:
                lo, hi = sorted(rng.sample(range(n + 1), 2))
                segment = left[0][lo:hi]
                rest = [j for j in right[0] if j not in segment]
                o = rest[:lo] + segment + rest[lo:]
            else:
                o = list(order)
            a = {j: (left[1][j] if rng.random() < 0.5 else right[1][j]) for j in o}
            if len(o) > 1 and rng.random() < 0.7:
                i, j = rng.sample(range(len(o)), 2)
                o[i], o[j] = o[j], o[i]
            if o and rng.random() < 0.8:
                j = rng.choice(o)
                a[j] = random_owner(j)
            next_population.append((o, a))
        population = next_population
        if len(evaluated) >= budget:
            break
    for item in population:
        evaluate(item)
    plans = [v for v in evaluated.values() if isfinite(v[0])]
    plans.sort(key=lambda v: (v[0], tuple(v[1][0]), tuple(v[1][1][j] for j in v[1][0])))
    return [p for _, p in plans], dict(
        proxy_evaluations=costs.evaluations,
        candidates=len(evaluated),
        pools={str(j): v for j, v in pools.items()} if soft else {},
    )
