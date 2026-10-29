"""Isolate single-leg planning from task matching, simulation and audit costs."""

from statistics import median
from time import perf_counter

from agv.io.storage import write_json
from agv.planning.astar import Router
from agv.planning.sipp import SafeIntervalRouter
from agv.runner.compat import greedy_action
from agv.runner.environment import Environment
from agv.warehouse.scenarios import Scenario, example
from agv.world.reservations import VertexReservations, reservations


def run_routing_benchmark(output):
    corridor = Scenario(3, 1, set(), set(), [(0, 0)], [], 500).check()
    cases = [
        (
            "long_wait",
            corridor,
            (0, 0),
            (2, 0),
            0,
            0,
            VertexReservations((t, (1, 0)) for t in range(1, 401)),
            set(),
            2,
        )
    ]
    scene = example(mode="dynamic", size="medium", vehicles=6, task_count=30, arrival="burst")
    env = Environment(scene)
    while not env.done and env.time < scene.horizon:
        env.assign(greedy_action(env.observe()))
        obs = env.observe()
        if env.time % 10 == 0:
            for v in obs["vehicles"]:
                if v["state"] not in ("to_pickup", "to_delivery"):
                    continue
                record = v["route_record"]
                job = v["active_task"]
                leg = "pickup" if v["state"] == "to_pickup" else "delivery"
                goal = tuple(record["pickup_point"]) if leg == "pickup" else tuple(job["delivery"])
                other = [
                    w["committed_path"] if not w["available"] else w["return_path"]
                    for w in obs["vehicles"]
                    if w["id"] != v["id"]
                ]
                vertices, edges = reservations(other, env.time)
                cases.append(
                    (
                        "warehouse_reservations",
                        scene,
                        tuple(v["position"]),
                        goal,
                        env.time,
                        v["id"],
                        vertices,
                        edges,
                        job[leg + "_service"],
                    )
                )
        env.advance(observe=False)
    rows = []
    for family, s, start, goal, now, k, vertices, edges, service in cases:
        answers = []
        for name, cls in [("astar", Router), ("sipp", SafeIntervalRouter)]:
            times = []
            last = None
            for _ in range(5):
                router = cls(s)
                begin = perf_counter()
                last = router.leg(start, goal, now, k, vertices, edges, service)
                times.append(perf_counter() - begin)
            answers.append(None if last is None else len(last))
            rows.append(
                dict(
                    family=family,
                    solver=name,
                    seconds=median(times),
                    **router.stats,
                    completion_length=answers[-1],
                )
            )
        if answers[0] != answers[1]:
            raise RuntimeError("SIPP earliest-finish differential failed")
    write_json(
        output,
        dict(
            cases=len(cases),
            repetitions=5,
            timing="median per case; includes reverse BFS heuristic construction",
            all_completion_lengths_equal=True,
            rows=rows,
        ),
    )
    return rows
