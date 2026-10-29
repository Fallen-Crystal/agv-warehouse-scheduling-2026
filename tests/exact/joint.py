"""Exact two-vehicle CP-SAT work trajectories plus exact joint return tails."""

import hashlib
import time
from fractions import Fraction
from heapq import heappop, heappush
from itertools import product
from math import lcm
from pathlib import Path

from ortools.sat.python import cp_model

from agv.evaluation.objectives.linear_f import checked_score
from tests.exact.fixtures import new_world as World


def joint_return_graph(scene):
    """All collision-free return states, no transit/parking through terminals."""
    cells = sorted(
        p for x in range(scene.width) for y in range(scene.height) if scene.free(p := (x, y))
    )
    states = [
        p
        for p in product(cells, repeat=2)
        if p[0] != p[1] and p[0] != scene.homes[1] and p[1] != scene.homes[0]
    ]
    available = set(states)
    incoming = {s: [] for s in states}
    ordinary = scene.transit_only | set(scene.homes)
    for state in states:
        options = []
        for k, p in enumerate(state):
            choices = [
                q for q in scene.neighbors(p) if q not in scene.stations and q != scene.homes[1 - k]
            ]
            if p in ordinary:
                choices.append(p)
            options.append(choices)
        for nxt in product(*options):
            if nxt not in available or nxt == state or (nxt[0] == state[1] and nxt[1] == state[0]):
                continue
            cost = sum(a != b for a, b in zip(state, nxt))
            incoming[nxt].append((state, cost))
    goal = tuple(scene.homes)
    dist = {goal: (0, 0)}
    successor = {}
    heap = [(0, 0, goal)]
    while heap:
        cost, steps, state = heappop(heap)
        if dist[state] != (cost, steps):
            continue
        for prev, edge in incoming[state]:
            value = cost + edge, steps + 1
            if value < dist.get(prev, (10**9, 10**9)):
                dist[prev] = value
                successor[prev] = state
                heappush(heap, (*value, prev))
    return cells, dist, successor


def tail_path(state, scene, successor):
    result = [state]
    goal = tuple(scene.homes)
    while result[-1] != goal:
        result.append(successor[result[-1]])
    return result


def coefficients(objective, n):
    terms = [
        Fraction(str(objective.weights[0])) / Fraction(str(objective.scales[0])),
        Fraction(str(objective.weights[1])) / (n * Fraction(str(objective.scales[1]))),
        Fraction(str(objective.weights[2])) / Fraction(str(objective.scales[2])),
    ]
    scale = lcm(*(v.denominator for v in terms))
    return tuple(int(v * scale) for v in terms), scale


def solve(model, objective, incumbent, *, seconds=120, model_path=None):
    if (
        model["vehicles"] != 2
        or model["close_at"] != 0
        or any(j["release"] != 0 for j in model["tasks"])
    ):
        raise ValueError("Reference scope is closed static two-vehicle problems")
    checked_score(model, incumbent, objective)
    start = time.perf_counter()
    world = World(model)
    world.publish_and_complete()
    jobs = list(model["tasks"])
    n = len(jobs)
    if len(world.bound) != n:
        raise ValueError("Exact fixture must have fixed initial WMS bindings")
    slots = [model["slots"][world.bound[j["id"]]] for j in jobs]
    if any(len(s["points"]) != 1 for s in slots):
        raise ValueError("Reference has fixed service sides")
    (ai, bi, ci), scale = coefficients(objective, n)
    upper = (
        ai * incumbent["T"] + bi * sum(r["end"] for r in incumbent["records"]) + ci * incumbent["D"]
    )
    horizon = upper // ai  # Any strictly better solution has T <= this bound.
    cells, tail_cost, successor = joint_return_graph(model["scene"])
    idx = {p: i for i, p in enumerate(cells)}
    scene = model["scene"]
    cp = cp_model.CpModel()
    pos = [
        [cp.new_int_var(0, len(cells) - 1, f"x{k}_{t}") for t in range(horizon + 1)]
        for k in range(2)
    ]
    for k in range(2):
        cp.add(pos[k][0] == idx[scene.homes[k]])
        for x in pos[k]:
            cp.add(x != idx[scene.homes[1 - k]])
    T = cp.new_int_var(0, horizon, "T")
    steps = []
    live = []
    for t in range(horizon + 1):
        b = cp.new_bool_var(f"live{t}")
        cp.add(T >= t).only_enforce_if(b)
        cp.add(T < t).only_enforce_if(b.Not())
        live.append(b)
        cp.add_all_different([pos[0][t], pos[1][t]])
    allowed = [(idx[p], idx[q]) for p in cells for q in [p, *scene.neighbors(p)]]
    swaps = [(idx[p], idx[q], idx[q], idx[p]) for p in cells for q in scene.neighbors(p)]
    moved = []
    for t in range(horizon):
        b = cp.new_bool_var(f"step{t}")
        cp.add(T > t).only_enforce_if(b)
        cp.add(T <= t).only_enforce_if(b.Not())
        steps.append(b)
        for k in range(2):
            cp.add_allowed_assignments([pos[k][t], pos[k][t + 1]], allowed)
            cp.add(pos[k][t + 1] == pos[k][t]).only_enforce_if(b.Not())
            m = cp.new_bool_var(f"move{k}_{t}")
            cp.add(pos[k][t] != pos[k][t + 1]).only_enforce_if(m)
            cp.add(pos[k][t] == pos[k][t + 1]).only_enforce_if(m.Not())
            moved.append(m)
        cp.add_forbidden_assignments([pos[0][t], pos[0][t + 1], pos[1][t], pos[1][t + 1]], swaps)
    event = []
    owner = []
    intervals = [[], []]
    bays = {}
    covers = {}
    active = {}
    past = {}

    def conjunction(conditions, name):
        b = cp.new_bool_var(name)
        cp.add_bool_and(conditions).only_enforce_if(b)
        cp.add_bool_or([x.Not() for x in conditions]).only_enforce_if(b.Not())
        return b

    def leq(v, t, name):
        b = cp.new_bool_var(name)
        cp.add(v <= t).only_enforce_if(b)
        cp.add(v > t).only_enforce_if(b.Not())
        return b

    for j, (job, slot) in enumerate(zip(jobs, slots)):
        ev = {
            key: cp.new_int_var(0, horizon, f"{key}{j}") for key in ("a", "pa", "pe", "da", "end")
        }
        pickup, drop, ps, ds = (
            (job["port"], slot["points"][0], 1, 2 * slot["level"])
            if job["kind"] == "delivery"
            else (slot["points"][0], job["port"], 2 * slot["level"], 1)
        )
        cp.add(ev["pa"] >= ev["a"])
        cp.add(ev["pe"] == ev["pa"] + ps)
        cp.add(ev["da"] >= ev["pe"])
        cp.add(ev["end"] == ev["da"] + ds)
        own = [cp.new_bool_var(f"owner{j}_{k}") for k in range(2)]
        cp.add_exactly_one(own)
        owner.append(own)
        event.append(ev)
        size = cp.new_int_var(0, horizon, f"size{j}")
        cp.add(size == ev["end"] - ev["a"])
        lock_end = ev["end"] if job["kind"] == "delivery" else ev["pe"]
        lock_size = cp.new_int_var(0, horizon, f"locksize{j}")
        cp.add(lock_size == lock_end - ev["a"])
        bays.setdefault(slot["bay"], []).append(
            cp.new_interval_var(ev["a"], lock_size, lock_end, f"bay{j}")
        )
        for k in range(2):
            intervals[k].append(
                cp.new_optional_interval_var(ev["a"], size, ev["end"], own[k], f"veh{j}_{k}")
            )
        for t in range(horizon + 1):
            begun = leq(ev["a"], t, f"begun{j}_{t}")
            finished = leq(ev["end"], t, f"done{j}_{t}")
            service_bounds = []
            for name, point, lo, hi in (
                ("pick", pickup, ev["pa"], ev["pe"]),
                ("drop", drop, ev["da"], ev["end"]),
            ):
                left = leq(lo, t, f"{name}lo{j}_{t}")
                right = leq(hi, t - 1, f"{name}hi{j}_{t}").Not()
                service_bounds.append((name, point, left, right))
            for k in range(2):
                active[j, k, t] = conjunction([own[k], begun, finished.Not()], f"act{j}_{k}_{t}")
                past[j, k, t] = conjunction([own[k], finished], f"past{j}_{k}_{t}")
                for name, point, left, right in service_bounds:
                    cover = conjunction([own[k], left, right], f"{name}{j}_{k}_{t}")
                    cp.add(pos[k][t] == idx[point]).only_enforce_if(cover)
                    if point in scene.stations:
                        covers.setdefault((k, t, point), []).append(cover)
    for item in intervals:
        cp.add_no_overlap(item)
    for item in bays.values():
        cp.add_no_overlap(item)
    for i, (ji, si) in enumerate(zip(jobs, slots)):
        for j, (jj, sj) in enumerate(zip(jobs, slots)):
            if i == j or si["bay"] != sj["bay"]:
                continue
            if ji["kind"] == jj["kind"] == "retrieval" and si["level"] > sj["level"]:
                cp.add(event[i]["pe"] <= event[j]["a"])
            if ji["kind"] == jj["kind"] == "delivery" and si["level"] < sj["level"]:
                cp.add(event[i]["end"] <= event[j]["a"])
    cp.add_max_equality(T, [ev["end"] for ev in event])
    ordinary = scene.transit_only | set(scene.homes)
    for k in range(2):
        for t in range(horizon + 1):
            for port in scene.stations:
                on = cp.new_bool_var(f"onport{k}_{t}_{idx[port]}")
                cp.add(pos[k][t] == idx[port]).only_enforce_if(on)
                cp.add(pos[k][t] != idx[port]).only_enforce_if(on.Not())
                cp.add_bool_or(covers.get((k, t, port), [])).only_enforce_if([on, live[t]])
            if t == horizon:
                continue
            stationary = cp.new_bool_var(f"still{k}_{t}")
            cp.add(pos[k][t] == pos[k][t + 1]).only_enforce_if(stationary)
            cp.add(pos[k][t] != pos[k][t + 1]).only_enforce_if(stationary.Not())
            # An unassigned car cannot depart home to anticipate a locked task.
            cp.add_bool_or(
                [active[j, k, t] for j in range(n)] + [past[j, k, t] for j in range(n)]
            ).only_enforce_if([steps[t], stationary.Not()])
            for point in set(cells) - ordinary:
                on = cp.new_bool_var(f"workwait{k}_{t}_{idx[point]}")
                cp.add(pos[k][t] == idx[point]).only_enforce_if(on)
                cp.add(pos[k][t] != idx[point]).only_enforce_if(on.Not())
                cp.add_bool_or([active[j, k, t] for j in range(n)]).only_enforce_if(
                    [on, stationary, steps[t]]
                )
    final = [cp.new_int_var(0, len(cells) - 1, f"final{k}") for k in range(2)]
    for k in range(2):
        cp.add_element(T, pos[k], final[k])
    tail = cp.new_int_var(0, max(v[0] for v in tail_cost.values()), "tail_moves")
    cp.add_allowed_assignments(
        final + [tail], [(idx[a], idx[b], v[0]) for (a, b), v in tail_cost.items()]
    )
    D = cp.new_int_var(0, 2 * horizon + max(v[0] for v in tail_cost.values()), "D")
    cp.add(D == sum(moved) + tail)
    expression = ai * T + bi * sum(ev["end"] for ev in event) + ci * D
    cp.add(expression <= upper)
    cp.minimize(expression)
    lookup = {r["task"]: r for r in incumbent["records"]}
    for j, job in enumerate(jobs):
        r = lookup[job["id"]]
        for key, field in (
            ("a", "assigned_at"),
            ("pa", "pickup_arrival"),
            ("pe", "pickup_end"),
            ("da", "drop_arrival"),
            ("end", "end"),
        ):
            cp.add_hint(event[j][key], r[field])
        for k in range(2):
            cp.add_hint(owner[j][k], int(k == r["vehicle"]))
    for k in range(2):
        for t in range(horizon + 1):
            cp.add_hint(pos[k][t], idx[tuple(incumbent["paths"][k][min(t, incumbent["T"])])])
    cp.add_hint(T, incumbent["T"])
    model_hash = None
    if model_path is not None:
        if not cp.export_to_file(str(model_path)):
            raise ValueError("Could not export exact integer model")
        model_hash = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.random_seed = 19
    status = solver.solve(cp)
    proof = dict(
        status=solver.status_name(status),
        optimal=status == cp_model.OPTIMAL,
        objective_integer=solver.objective_value
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        else None,
        bound_integer=solver.best_objective_bound,
        coefficient_scale=scale,
        coefficients=[ai, bi, ci],
        incumbent_integer=upper,
        derived_work_horizon=horizon,
        exact_joint_tail_states=len(tail_cost),
        solver_seconds=solver.wall_time,
        total_wall=time.perf_counter() - start,
        branches=solver.num_branches,
        exported_model_sha256=model_hash,
        solver_version="ortools-9.15.6755",
        model_stats=cp.model_stats(),
        response_stats=solver.response_stats(),
        scope="static two-car reduced geometry; fixed WMS slots; joint assignment, paths and exact return; no fixed-SIPP-strategy certificate",
    )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return proof, None
    done = solver.value(T)
    paths = [[cells[solver.value(pos[k][t])] for t in range(done + 1)] for k in range(2)]
    tail_route = tail_path(tuple(p[-1] for p in paths), scene, successor)
    for k in range(2):
        paths[k].extend(s[k] for s in tail_route[1:])
    records = []
    for j, (job, slot, ev) in enumerate(zip(jobs, slots, event)):
        k = next(k for k in range(2) if solver.boolean_value(owner[j][k]))
        pickup, drop = (
            (job["port"], slot["points"][0])
            if job["kind"] == "delivery"
            else (slot["points"][0], job["port"])
        )
        records.append(
            dict(
                task=job["id"],
                vehicle=k,
                slot=slot["id"],
                assigned_at=solver.value(ev["a"]),
                pickup=pickup,
                drop=drop,
                pickup_arrival=solver.value(ev["pa"]),
                pickup_end=solver.value(ev["pe"]),
                drop_arrival=solver.value(ev["da"]),
                end=solver.value(ev["end"]),
            )
        )
    result = as_result(model, paths, records, objective)
    score = checked_score(model, result, objective)
    if abs(score["F_linear_v2"] - solver.objective_value / scale) > 1e-10:
        raise ValueError("CP objective differs from physical replay")
    proof["audit"] = score
    proof["objective_integer_verified"] = round(solver.objective_value)
    return proof, result


def as_result(model, paths, records, objective):
    end = len(paths[0]) - 1
    labels = []
    for k, path in enumerate(paths):
        tags = []
        for t in range(end):
            r = next(
                (r for r in records if r["vehicle"] == k and r["assigned_at"] <= t < r["end"]), None
            )
            if r is None:
                tag = "standby" if path[t] == path[t + 1] else "empty"
            elif r["pickup_arrival"] <= t < r["pickup_end"] or r["drop_arrival"] <= t < r["end"]:
                tag = "service"
            elif r["pickup_end"] <= t < r["drop_arrival"]:
                tag = "loaded"
            else:
                tag = "empty"
            tags.append(tag)
        labels.append(tags)
    decisions = [
        dict(
            time=t,
            pairs=[(r["vehicle"], r["task"]) for r in records if r["assigned_at"] == t],
            visible_ids=[j["id"] for j in model["tasks"]],
        )
        for t in sorted({r["assigned_at"] for r in records})
    ]
    moves = sum(a != b for path in paths for a, b in zip(path, path[1:]))
    stock = set(model["occupied"])
    jobs = {j["id"]: j for j in model["tasks"]}
    for r in records:
        if jobs[r["task"]]["kind"] == "delivery":
            stock.add(r["slot"])
        else:
            stock.remove(r["slot"])
    loaded = sum(
        paths[r["vehicle"]][t] != paths[r["vehicle"]][t + 1]
        for r in records
        for t in range(r["pickup_end"], r["drop_arrival"])
    )
    return dict(
        valid=True,
        method="cp_sat_joint",
        paths=paths,
        labels=labels,
        time=end,
        records=records,
        completed=sorted(jobs),
        decisions=decisions,
        T=max(r["end"] for r in records),
        R=sum(r["end"] - jobs[r["task"]]["release"] for r in records) / len(records),
        D=moves,
        empty_distance=moves - loaded,
        final_stock=sorted(stock),
        objective=objective.to_dict(),
    )
