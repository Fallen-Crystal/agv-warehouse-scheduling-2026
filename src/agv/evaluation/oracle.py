"""Restricted exact scheduler for very small static instances.

The oracle enumerates every task-to-vehicle assignment and every global task
order, then executes each candidate in the real Environment (including vertex
and edge reservations).  It deliberately does not insert extra empty actions,
so it proves optimality only within the no-deliberate-wait schedule class; that
is still a useful lower-bound check for online heuristics.

Intended for <=5 tasks and <=2 vehicles as an offline optimality-gap tool,
not an online policy and not part of formal large-scale benchmarks.
"""

from itertools import permutations, product

from agv.evaluation.validation import validate
from agv.simulation import Environment


def exact_static(scenario, max_tasks=5, max_vehicles=2):
    if any(j.release != 0 for j in scenario.tasks):
        raise ValueError("Oracle only supports static tasks released at 0")
    if len(scenario.tasks) > max_tasks or len(scenario.homes) > max_vehicles:
        raise ValueError("Instance too large for the restricted oracle")
    jobs = scenario.tasks
    n, vehicles = len(jobs), len(scenario.homes)
    job_index = {job.id: i for i, job in enumerate(jobs)}
    best = None
    best_plan = None
    evaluated = 0
    for assignment in product(range(vehicles), repeat=n):
        for order in permutations(jobs):
            env = Environment(scenario)
            ok = True
            for job in order:
                k = assignment[job_index[job.id]]
                while env._active[k] is not None and (
                    scenario.horizon is None or env.time < scenario.horizon
                ):
                    env.advance(observe=False)
                if env._active[k] is not None:
                    ok = False
                    break
                response = env.assign([(k, job.id)])
                if not response or not response[0]["accepted"]:
                    ok = False
                    break
            if not ok:
                continue
            while not env.done and (scenario.horizon is None or env.time < scenario.horizon):
                env.advance(observe=False)
            if not env.done:
                continue
            result = env.result()
            validate(scenario, result)
            value = (result["mean_flow_time"], result["makespan"], result["moves"])
            evaluated += 1
            if best is None or value < best:
                best, best_plan = value, result
    if best is None:
        raise ValueError("No feasible schedule found within the horizon")
    return dict(
        best_plan,
        oracle=dict(
            mean_flow_time=best[0],
            makespan=best[1],
            moves=best[2],
            evaluated_orders=evaluated,
            schedule_class="no-deliberate-wait schedules",
        ),
    )
