import random


def order_candidates(self, *, objective, seed=0, population=12, generations=10, budget=144):
    """Permutation GA: tournament selection, order crossover, swap mutation.

    Elitism preserves the best proxy candidate. It gives no approximation
    guarantee; candidates are subsequently checked by true SIPP rollouts.
    """
    self.allowance = budget
    ids = list(self.jobs)
    if len(ids) < 2:
        return [(ids, self.owners(ids), "order_ga")]
    rng = random.Random(seed)
    cache = {}

    def fitness(order):
        key = tuple(order)
        if key not in cache:
            cache[key] = sum(
                w * v / d
                for w, v, d in zip(objective.weights, self.estimate(order), objective.scales)
            )
        return cache[key], key

    pool = [ids, ids[::-1], sorted(ids, key=lambda k: (self.jobs[k]["release"], k))]
    while len(pool) < population:
        pool.append(rng.sample(ids, len(ids)))
    for _ in range(generations):
        pool.sort(key=fitness)
        new = pool[:2]
        while len(new) < population:
            a = min(rng.sample(pool, 3), key=fitness)
            b = min(rng.sample(pool, 3), key=fitness)
            left, right = sorted(rng.sample(range(len(ids) + 1), 2))
            segment = a[left:right]
            rest = [x for x in b if x not in segment]
            child = rest[:left] + segment + rest[left:]
            if rng.random() < 0.5:
                i, j = rng.sample(range(len(ids)), 2)
                child[i], child[j] = child[j], child[i]
            new.append(child)
        pool = new
    ranked = sorted(cache, key=lambda k: (cache[k], k))
    return [(list(k), self.owners(k), "order_ga") for k in ranked[:4] if cache[k] < float("inf")]
