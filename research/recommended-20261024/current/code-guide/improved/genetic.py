"""One joint GA: sequence plus owner genes; no separate matching or repair."""

import random
from math import isfinite
from v2.ranking import rank_score


def candidates(
    costs,
    order,
    owners,
    *,
    objective,
    soft=False,
    seed=0,
    budget=96,
    generations=8,
    local_seeds=False,
    seed_plans=None,
):
    rng = random.Random(seed)
    costs.allowance = budget
    vehicle_count = len(costs.obs["vehicles"])
    vehicle_pools = {}
    for task_id in order:
        job = costs.jobs[task_id]
        options = []
        target_region = costs.slots[task_id]["shelf"][1] >= costs.world.scene.height / 2
        local = []
        for vehicle_id, vehicle in enumerate(costs.obs["vehicles"]):
            active = costs.world.active[vehicle_id]
            position = active["drop"] if active else vehicle["position"]
            available = (
                max(costs.world.time, active["end"]) if active else costs.world.time
            )
            distance = costs.details(vehicle_id, position, job)[0]
            options.append((available + distance, vehicle_id))
            if (position[1] >= costs.world.scene.height / 2) == target_region:
                local.append(vehicle_id)
        vehicle_pools[task_id] = sorted(
            set(local) | {vehicle_id for _, vehicle_id in sorted(options)[:3]}
        )
    evaluated = {}

    def evaluate(item):
        task_order, vehicle_by_task = item
        key = (
            tuple(task_order),
            tuple(vehicle_by_task[task_id] for task_id in task_order),
        )
        if key not in evaluated:
            if len(evaluated) >= budget:
                return float("inf")
            values = costs.estimate_joint(task_order, vehicle_by_task)
            score = rank_score(values, objective)
            evaluated[key] = (score, (list(task_order), dict(vehicle_by_task), "ga"))
        return evaluated[key][0]

    def random_owner(task_id):
        choices = (
            vehicle_pools[task_id]
            if soft and rng.random() < 0.75
            else list(range(vehicle_count))
        )
        return rng.choice(choices)

    population = [(list(order), dict(owners))]
    for index in range(11):
        task_order = list(order)
        vehicle_by_task = dict(owners)
        if local_seeds and index < 8:
            # Most seeds retain a feasible schedule's structure instead of
            # simultaneously randomizing every task's vehicle and order.
            if index < 4 and task_order:
                task_id = rng.choice(task_order)
                alternatives = [
                    vehicle_id
                    for vehicle_id in range(vehicle_count)
                    if vehicle_id != vehicle_by_task[task_id]
                ]
                if alternatives:
                    vehicle_by_task[task_id] = rng.choice(alternatives)
            elif len(task_order) > 1:
                i, task_id = rng.sample(range(len(task_order)), 2)
                if index < 6:
                    task_order[i], task_order[task_id] = (
                        task_order[task_id],
                        task_order[i],
                    )
                else:
                    task_order.insert(task_id, task_order.pop(i))
        else:
            rng.shuffle(task_order)
            vehicle_by_task = {task_id: random_owner(task_id) for task_id in task_order}
        population.append((task_order, vehicle_by_task))
    for index, (task_order, vehicle_by_task, kind) in enumerate((seed_plans or [])[:2]):
        if (
            len(task_order) != len(order)
            or set(task_order) != set(order)
            or set(vehicle_by_task) != set(order)
        ):
            raise ValueError("Incomplete Hungarian seed")
        population[index + 1] = (list(task_order), dict(vehicle_by_task))
    for _ in range(generations):
        population.sort(
            key=lambda x: (
                evaluate(x),
                tuple(x[0]),
                tuple(x[1][task_id] for task_id in x[0]),
            )
        )
        next_population = [
            (list(task_order), dict(vehicle_by_task))
            for task_order, vehicle_by_task in population[:2]
        ]
        while len(next_population) < 12:
            left = min(rng.sample(population, min(3, len(population))), key=evaluate)
            right = min(rng.sample(population, min(3, len(population))), key=evaluate)
            task_count = len(order)
            if task_count > 1:
                segment_start, segment_end = sorted(
                    rng.sample(range(task_count + 1), 2)
                )
                segment = left[0][segment_start:segment_end]
                rest = [task_id for task_id in right[0] if task_id not in segment]
                task_order = rest[:segment_start] + segment + rest[segment_start:]
            else:
                task_order = list(order)
            vehicle_by_task = {
                task_id: (left[1][task_id] if rng.random() < 0.5 else right[1][task_id])
                for task_id in task_order
            }
            if len(task_order) > 1 and rng.random() < 0.7:
                i, task_id = rng.sample(range(len(task_order)), 2)
                task_order[i], task_order[task_id] = task_order[task_id], task_order[i]
            if task_order and rng.random() < 0.8:
                task_id = rng.choice(task_order)
                vehicle_by_task[task_id] = random_owner(task_id)
            next_population.append((task_order, vehicle_by_task))
        population = next_population
        if len(evaluated) >= budget:
            break
    for item in population:
        evaluate(item)
    plans = [vehicle for vehicle in evaluated.values() if isfinite(vehicle[0])]
    plans.sort(
        key=lambda vehicle: (
            vehicle[0],
            tuple(vehicle[1][0]),
            tuple(vehicle[1][1][task_id] for task_id in vehicle[1][0]),
        )
    )
    return [p for _, p in plans], dict(
        proxy_evaluations=costs.evaluations,
        candidates=len(evaluated),
        pools={
            str(task_id): vehicle for task_id, vehicle in vehicle_pools.items()
        }
        if soft
        else {},
    )
