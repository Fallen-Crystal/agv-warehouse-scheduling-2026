"""Course-report joint assignment and certificate-triggered counterfactual rollout."""

from collections import defaultdict, deque
from dataclasses import dataclass
from math import isclose, isfinite
from time import perf_counter
from types import FunctionType

import paths  # noqa: F401  (bootstraps the frozen runtime's engine imports)
from improved.execute import run as frozen_run
from objective import LinearObjective, checked_score
from ortools.sat.python import cp_model
from wepa.data import build
from wepa.kernel import World
from wepa.search import snapshot, values


def order_group(job):
    return job["sku"], job["kind"], tuple(job["port"])


def reserve(world, job, slot):
    world.bound[job["id"]] = slot
    reservations = world.in_reserved if job["kind"] == "delivery" else world.out_reserved
    reservations[slot] = job["id"]


class JointWorld(World):
    """Keep the kernel's physical transitions and release uncommitted WMS bindings."""

    def publish_and_complete(self):
        super().publish_and_complete()
        for jid in self.visible.keys() - self.assigned:
            self.bound.pop(jid, None)
        self.in_reserved = {
            sid: jid for sid, jid in self.in_reserved.items() if jid in self.assigned
        }
        self.out_reserved = {
            sid: jid for sid, jid in self.out_reserved.items() if jid in self.assigned
        }

    def legal_slots(self):
        by_bay = defaultdict(list)
        for slot in self.slots:
            by_bay[slot["bay"]].append(slot)
        reserved_bays = {
            self.slots[sid]["bay"] for sid in self.in_reserved.keys() | self.out_reserved.keys()
        }
        legal = defaultdict(list)
        for bay, slots in by_bay.items():
            if self.locks.get(bay, 0) > self.time or bay in reserved_bays:
                continue
            slots.sort(key=lambda slot: slot["level"])
            occupied = [slot for slot in slots if slot["id"] in self.stock]
            if occupied:
                top = occupied[-1]
                legal[top["sku"], "retrieval"].append(top["id"])
            lowest = next((slot for slot in slots if slot["id"] not in self.stock), None)
            if lowest is not None and all(
                slot["id"] in self.stock for slot in slots if slot["level"] < lowest["level"]
            ):
                legal[lowest["sku"], "delivery"].append(lowest["id"])
        return legal

    def ready(self):
        legal = self.legal_slots()
        jobs = []
        for jid, job in self.visible.items():
            if jid in self.assigned:
                continue
            if jid not in self.bound:
                if legal.get((job["sku"], job["kind"])):
                    jobs.append(job)
                continue
            sid = self.bound[jid]
            slot = self.slots[sid]
            if self.locks.get(slot["bay"], 0) > self.time:
                continue
            if job["kind"] == "retrieval":
                if sid in self.stock and self.out_reserved.get(sid) == jid and not any(
                    other["bay"] == slot["bay"] and other["level"] > slot["level"]
                    and other["id"] in self.stock for other in self.slots
                ):
                    jobs.append(job)
            elif sid not in self.stock and self.in_reserved.get(sid) == jid and all(
                other["id"] in self.stock for other in self.slots
                if other["bay"] == slot["bay"] and other["level"] < slot["level"]
            ):
                jobs.append(job)
        return jobs


@dataclass(frozen=True)
class _Option:
    car: int
    group: tuple
    slot: int
    bay: str
    duration: int
    distance: int

    @property
    def assignment(self):
        return self.car, self.group, self.slot


class JointPolicy:
    """Maximize current batch size, then minimize the report's integer proxy cost."""

    def __init__(self, seed, *, objective, allocation="joint"):
        if allocation not in ("joint", "fixed"):
            raise ValueError("allocation must be 'joint' or 'fixed'")
        self.seed = seed
        self.objective = objective
        self.allocation = allocation
        self.logs = []
        self.excluded_assignment = None
        self.certificate = None

    def _options(self, world, cars, groups):
        legal = world.legal_slots() if self.allocation == "joint" else None
        options = []
        for group, jobs in sorted(groups.items()):
            sku, kind, port = group
            slots = legal[sku, kind] if legal is not None else [world.bound[j["id"]] for j in jobs]
            for sid in slots:
                slot = world.slots[sid]
                for car in cars:
                    start = world.plans[car][0]
                    home = world.scene.homes[car]
                    for point in slot["points"]:
                        pickup, drop = (port, point) if kind == "delivery" else (point, port)
                        empty = world.router.distance(start, pickup, car)
                        loaded = world.router.distance(pickup, drop, car)
                        duration = empty + loaded + 1 + 2 * slot["level"]
                        delta = (empty + loaded + world.router.distance(drop, home, car)
                                 - world.router.distance(start, home, car))
                        if isfinite(duration) and isfinite(delta):
                            options.append(_Option(car, group, sid, slot["bay"],
                                                   int(duration), int(delta)))
        return options

    def _trial(self, world, chosen, groups):
        view = snapshot(world, fast=False)
        if self.allocation == "joint":
            view.__class__ = JointWorld
        plans = []
        used = defaultdict(int)
        for _, option in chosen:
            jobs = groups[option.group]
            if self.allocation == "joint":
                job = jobs[used[option.group]]
                used[option.group] += 1
                reserve(view, job, option.slot)
            else:
                job = next(j for j in jobs if view.bound[j["id"]] == option.slot)
            # The appendix uses each side's proxy in the model and delegates the
            # actual side choice to the frozen SIPP trip planner.
            proposal = view.trip(option.car, job)
            if proposal is None:
                return None
            view.commit(option.car, job, proposal)
            plans.append((option, job, proposal))
        return plans

    def action(self, world):
        cars = [car for car, record in enumerate(world.active) if record is None]
        groups = defaultdict(list)
        for job in world.ready():
            groups[order_group(job)].append(job)
        for jobs in groups.values():
            jobs.sort(key=lambda job: (job["release"], job["id"]))
        options = self._options(world, cars, groups)
        if not options:
            self.certificate = dict(candidates=0, physical_conflict_cuts=0, assignments=[])
            return []

        model = cp_model.CpModel()
        selected = [model.new_bool_var(f"x{i}") for i in range(len(options))]
        for key, keys in (("car", cars), ("bay", sorted({o.bay for o in options})),
                          ("group", sorted(groups))):
            for value in keys:
                capacity = len(groups[value]) if key == "group" else 1
                model.add(sum(x for x, o in zip(selected, options) if getattr(o, key) == value)
                          <= capacity)
        if self.excluded_assignment is not None:
            for x, option in zip(selected, options):
                if option.assignment == self.excluded_assignment:
                    model.add(x == 0)
        fixed = max([world.time] + [record["end"] for record in world.active if record])
        horizon = max(fixed, world.time + max(o.duration for o in options))
        finish = model.new_int_var(fixed, horizon, "batch_finish")
        for x, option in zip(selected, options):
            model.add(finish >= world.time + option.duration).only_enforce_if(x)
        n = len(world.visible)
        costs = [9 * option.duration + n * option.distance for option in options]
        local_cost = 15 * n * finish + sum(cost * x for cost, x in zip(costs, selected))
        # Equation (65). Include a bound for negative increments if the router allows any.
        upper = 15 * n * horizon + len(cars) * max(0, max(costs))
        lower = len(cars) * min(0, min(costs))
        model.minimize(local_cost + (upper - lower + 1) * (len(cars) - sum(selected)))
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = self.seed
        cuts = 0
        while True:
            status = solver.solve(model)
            if status != cp_model.OPTIMAL:
                raise RuntimeError(f"Joint assignment solve failed: {solver.status_name(status)}")
            chosen = [(i, option) for i, (x, option) in enumerate(zip(selected, options))
                      if solver.value(x)]
            chosen.sort(key=lambda item: (item[1].duration, item[1].car, item[1].slot))
            plans = self._trial(world, chosen, groups)
            if plans is not None:
                break
            # Equation (66) excludes the whole failed bit vector. Another batch
            # can replace an idle vehicle's old suffix and free an obstructed route.
            rejected = {i for i, _ in chosen}
            model.add_bool_or([~x if i in rejected else x for i, x in enumerate(selected)])
            cuts += 1

        pairs = []
        allocations = []
        for option, job, proposal in plans:
            if self.allocation == "joint":
                reserve(world, job, option.slot)
            world.commit(option.car, job, proposal)
            pairs.append((option.car, job["id"]))
            allocations.append(dict(vehicle=option.car, task=job["id"], slot=option.slot))
        self.certificate = dict(
            time=world.time, visible_ids=sorted(world.visible), candidates=len(options),
            assignments=allocations, solver_status="OPTIMAL", predicted_finish=solver.value(finish),
            objective_integer=solver.objective_value, physical_conflict_cuts=cuts,
        )
        self.logs.append(self.certificate)
        return pairs


class RootPolicy(JointPolicy):
    """Solve the same joint batch with an optional equation (70) root exclusion."""

    def __init__(self, seed, *, objective=None, excluded_assignment=None):
        super().__init__(seed, objective=objective)
        self.excluded_assignment = excluded_assignment


def decision(world, policy):
    before = len(world.records)
    policy.action(world)
    return dict(time=world.time, proposals=[
        dict(record=dict(record), path=list(world.plans[record["vehicle"]]))
        for record in world.records[before:]
    ])


def root_candidate(world, seed, excluded_assignment=None):
    view = snapshot(world, fast=False)
    view.__class__ = JointWorld
    policy = RootPolicy(seed, excluded_assignment=excluded_assignment)
    step = decision(view, policy)
    return dict(step=step, certificate=policy.certificate, excluded_assignment=excluded_assignment)


def replay(world, step):
    if world.time != step["time"]:
        raise ValueError("Decision time differs from the certified trajectory")
    pairs = []
    for proposal in step["proposals"]:
        record, path = proposal["record"], proposal["path"]
        job = world.visible[record["task"]]
        sid, car = record["slot"], record["vehicle"]
        if (record["assigned_at"] != world.time or not path
                or path[0] != world.plans[car][0] or path[-1] != world.scene.homes[car]
                or sid not in world.legal_slots().get((job["sku"], job["kind"]), ())):
            raise ValueError("Recorded proposal is incompatible with the replay state")
        reserve(world, job, sid)
        world.commit(car, job, (list(path), dict(record)))
        pairs.append((car, job["id"]))
    return pairs


def plan_signature(step):
    # Timing stamps are included so a deduplicated/cached branch has the same
    # executed state transition even if two plans use identical grid positions.
    return tuple((tuple(sorted(p["record"].items())), tuple(p["path"]))
                 for p in step["proposals"])


def forecast(world, objective, seed, first_step=None):
    if not world.closed:
        raise ValueError("A complete suffix requires a closed order stream")
    view = snapshot(world, fast=False)
    view.__class__ = JointWorld
    policy = JointPolicy(seed, objective=objective)
    if first_step is None:
        first_step = root_candidate(world, seed)["step"]
    replay(view, first_step)
    steps = [first_step]
    view.advance()
    limit = world.time + max(3000, len(view.tasks) * 150)
    while view.time <= limit:
        view.publish_and_complete()
        if view.done:
            metrics = values(view)
            return dict(cost=objective.score(metrics), T=metrics[0], R=metrics[1], D=metrics[2],
                        steps=steps, physical_conflict_cuts=sum(
                            item["physical_conflict_cuts"] for item in policy.logs))
        if any(item is None for item in view.active) and view.ready():
            steps.append(decision(view, policy))
        view.advance()
    raise RuntimeError("Counterfactual suffix exceeded the physical execution limit")


class CounterfactualPolicy:
    """Replan only on closure and retain the cheapest verified complete reference."""

    def __init__(self, seed, *, objective, branch_budget=None):
        if branch_budget is not None and (type(branch_budget) is not int or branch_budget < 0):
            raise ValueError("branch_budget must be None or a nonnegative integer")
        self.seed = seed
        self.objective = objective
        self.branch_budget = branch_budget
        self.base_policy = JointPolicy(seed, objective=objective)
        self.plan = deque()
        self.known_ids = None
        self.incumbent_cost = None
        self.logs = []

    def action(self, world):
        if not world.closed:
            if self.known_ids is not None:
                raise ValueError("Order stream reopened after closure")
            pairs = self.base_policy.action(world)
            self.logs.append(dict(time=world.time, visible_ids=sorted(world.visible),
                                  phase="stream", replanned=False))
            return pairs

        known_ids = tuple(sorted(world.visible))
        if self.known_ids is not None and known_ids != self.known_ids:
            raise ValueError("An order was published after the stream closed")
        self.known_ids = known_ids
        if self.plan and world.time != self.plan[0]["time"]:
            raise ValueError("Decision time differs from the retained trajectory")
        if self.plan and not self.plan[0]["proposals"]:
            self.logs.append(dict(time=world.time, visible_ids=list(known_ids),
                                  phase="closed", replanned=False))
            return replay(world, self.plan.popleft())

        base = root_candidate(world, self.seed)
        candidates = [base]
        signatures = {plan_signature(base["step"])}
        for item in base["step"]["proposals"][:self.branch_budget]:
            record = item["record"]
            assignment = record["vehicle"], order_group(world.visible[record["task"]]), record["slot"]
            candidate = root_candidate(world, self.seed, assignment)
            signature = plan_signature(candidate["step"])
            if signature not in signatures:
                signatures.add(signature)
                candidates.append(candidate)

        branches = []
        for index, candidate in enumerate(candidates):
            if (index == 0 and self.plan
                    and plan_signature(candidate["step"]) == plan_signature(self.plan[0])):
                branches.append(dict(cost=self.incumbent_cost, steps=list(self.plan), cached=True))
            else:
                branches.append(dict(forecast(world, self.objective, self.seed, candidate["step"]),
                                     cached=False))
        chosen = min(range(len(branches)), key=lambda index: (branches[index]["cost"], index))
        prior = self.incumbent_cost
        selected = branches[chosen]
        retained = bool(self.plan) and self.incumbent_cost <= selected["cost"]
        if not retained:
            if prior is not None and not self.plan:
                raise ValueError("Retained trajectory ended before the next dispatch decision")
            self.plan = deque(selected["steps"])
            self.incumbent_cost = selected["cost"]
        self.logs.append(dict(
            time=world.time, visible_ids=list(known_ids), phase="closed", replanned=True,
            candidates=[dict(cost=branch["cost"], cached=branch["cached"],
                             excluded_assignment=candidate["excluded_assignment"])
                        for branch, candidate in zip(branches, candidates)],
            selected=chosen, retained_incumbent=retained, reference_cost=prior,
            selected_cost=self.incumbent_cost, predicted_gain=branches[0]["cost"] - self.incumbent_cost,
            planned_decisions=len(self.plan),
        ))
        return replay(world, self.plan.popleft())


def _run(model, seed, objective, world_type, policy):
    # The frozen runner has no policy_factory. Its eta branch dispatches via
    # batch, which permits per-call injection without editing the archive or
    # mutating module globals. Keep all routing setup and result metrics frozen.
    bindings = dict(frozen_run.__globals__, World=world_type,
                    batch=lambda world, method: policy.action(world))
    run = FunctionType(frozen_run.__code__, bindings, argdefs=frozen_run.__defaults__)
    result = run(model, "eta", seed, objective=objective)
    result["search_log"] = policy.logs
    return result


def _prepare(case, protocol):
    close_at = case["close_at"]
    if type(close_at) is not int or close_at < 0:
        raise ValueError("close_at must be a nonnegative integer publisher event time")
    if any(job["release"] > close_at for job in case["tasks"]):
        raise ValueError("A case cannot release an order after its explicit close_at")
    model = build(case, **protocol["configuration"])
    objective = LinearObjective(**protocol["objective"])
    return model, objective


def _checked_row(case, model, objective, policy, result, allocation, algorithm, elapsed):
    scoring = checked_score(model, result, objective)
    if not scoring["audit"]["valid"]:
        raise ValueError("Course-report trajectory failed independent validation")
    score = scoring["F_linear_v2"]
    if isinstance(policy, CounterfactualPolicy):
        if policy.plan or (policy.incumbent_cost is not None and not isclose(
            score, policy.incumbent_cost, rel_tol=0, abs_tol=1e-12
        )):
            raise ValueError("Execution diverged from the retained complete trajectory")
        actions = dict(certified_refinements=sum(item["replanned"] for item in policy.logs),
                       stream_assignments=sum(item["phase"] == "stream" for item in policy.logs))
    else:
        actions = dict(joint_assignment=len(policy.logs))
    return dict(case=case["case"], valid=True, F=score,
                **{key: result[key] for key in ("T", "R", "D", "traffic_wait")},
                wall=perf_counter() - elapsed, actions=actions, ga_searches=[],
                allocation=allocation, algorithm=algorithm)


def execute(case, protocol, seed=0, allocation="joint"):
    model, objective = _prepare(case, protocol)
    policy = JointPolicy(seed, objective=objective, allocation=allocation)
    elapsed = perf_counter()
    result = _run(model, seed, objective, JointWorld if allocation == "joint" else World, policy)
    row = _checked_row(case, model, objective, policy, result, allocation,
                       "joint-inventory-cpsat-v1", elapsed)
    return row, result


def execute_counterfactual(case, protocol, seed=0, *, branch_budget=None):
    model, objective = _prepare(case, protocol)
    policy = CounterfactualPolicy(seed, objective=objective, branch_budget=branch_budget)
    elapsed = perf_counter()
    result = _run(model, seed, objective, JointWorld, policy)
    row = _checked_row(case, model, objective, policy, result, "joint",
                       "certificate-triggered-world-model-v5", elapsed)
    return row, result
