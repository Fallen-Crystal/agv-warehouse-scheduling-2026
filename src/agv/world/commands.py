"""Atomic command validation and commit. All route/record mutations live here."""

from copy import deepcopy
from dataclasses import dataclass

from agv.world.itinerary import Itinerary


@dataclass(frozen=True)
class Assign:
    vehicle: int
    task: int
    pickup: tuple[int, int] | None = None


@dataclass(frozen=True)
class Reposition:
    vehicle: int
    target: tuple[int, int]


@dataclass(frozen=True)
class Hold:
    vehicle: int
    steps: int = 1


@dataclass(frozen=True)
class ReplaceSuffix:
    proposal: dict


class CommandGate:
    """One write gateway. Assignment batches retain ordered per-pair feedback."""

    def apply(self, world, commands):
        commands = list(commands)
        if all(isinstance(cmd, Assign) for cmd in commands):
            return _assign(
                world,
                [
                    (c.vehicle, c.task) if c.pickup is None else (c.vehicle, c.task, c.pickup)
                    for c in commands
                ],
            )
        if len(commands) != 1:
            raise ValueError("Non-assignment commands must be committed individually")
        command = commands[0]
        if isinstance(command, Hold):
            return hold_return(world, command.vehicle, command.steps)
        if isinstance(command, Reposition):
            return reposition(world, command.vehicle, command.target)
        if isinstance(command, ReplaceSuffix):
            return _apply_replan(world, command.proposal)
        raise ValueError("Unknown world command")

    def assign(self, world, pairs):
        return _assign(world, pairs)


def _assign(self, pairs):
    """有序(vehicle_id,task_id)列表。非法输入整批拒绝；规划失败逐对报告。

    每辆车/任务每批最多出现一次。合法批次按输入顺序预约，先提交者优先。
    已取货任务不可取消；本版本从指派成功开始锁定到卸货结束。
    """
    if isinstance(pairs, (str, bytes, dict)):
        raise ValueError("Actions must be an iterable of vehicle/task pairs")
    try:
        pairs = list(pairs)
    except TypeError as error:
        raise ValueError("Actions must be an iterable of vehicle/task pairs") from error
    ks, js, normalized = [], [], []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) not in (2, 3):
            raise ValueError("Expected (vehicle_id, task_id[, pickup_point])")
        k, j = pair[:2]
        if type(k) is not int or not 0 <= k < len(self._plans) or self._active[k] is not None:
            raise ValueError("Unknown or busy vehicle")
        if (
            type(j) is not int
            or j not in self._jobs
            or j in self._assigned
            or self._jobs[j].release > self.time
        ):
            raise ValueError("Unknown, assigned or unreleased task")
        if not self.ruleset.dispatchable(self._jobs[j], self._records, self._assigned, self.time)[
            0
        ]:
            raise ValueError("Task blocked by same-face layer order or active pickup")
        selected = None
        if len(pair) == 3:
            raw = pair[2]
            if (
                not isinstance(raw, (list, tuple))
                or len(raw) != 2
                or any(type(x) is not int for x in raw)
            ):
                raise ValueError("Pickup point must contain two integer coordinates")
            selected = tuple(raw)
            if selected not in self._scenario.pickup_candidates(self._jobs[j]):
                raise ValueError("Pickup point is not a legal candidate")
        normalized.append((k, j, selected))
        ks.append(k)
        js.append(j)
    if len(set(ks)) != len(ks) or len(set(js)) != len(js):
        raise ValueError("Duplicate vehicle or task in batch")
    if self._scenario.uses_layer_rules and len({self._jobs[j].shelf for j in js}) != len(js):
        raise ValueError("Only one order per shelf face per dispatch batch")
    responses = []
    for k, j, selected in normalized:
        vertices, edges = self.plan_reservations().view_excluding(k, self.time)
        job = self._jobs[j]
        # 不同相邻停靠格可独立装货；同格占用仍由车辆路径预约约束。
        path, record, failed, attempts = self.services.plan_task(
            self._scenario,
            self._router,
            job,
            k,
            self._plans[k][0],
            self.time,
            vertices,
            edges,
            selected_pickup=selected,
        )
        if failed:
            self._planning_failures.append(
                dict(
                    time=self.time,
                    vehicle=k,
                    task_id=j,
                    failed_leg=failed,
                    reason="no_route_within_horizon",
                    candidate_attempts=attempts,
                )
            )
            responses.append(
                dict(
                    vehicle=k,
                    task_id=j,
                    accepted=False,
                    reason="no_route_within_horizon",
                    failed_leg=failed,
                )
            )
            continue
        self._idle_hold_counts[k] = 0
        self._idle_waits = [
            {**w, "end": min(w["end"], self.time)} if w["vehicle"] == k else w
            for w in self._idle_waits
        ]
        self._idle_waits = [w for w in self._idle_waits if w["end"] > w["start"]]
        self._replace_plan(k, path)
        self._position_targets[k] = None
        self._position_events = [
            e for e in self._position_events if not (e["vehicle"] == k and e["start"] == self.time)
        ]
        self._records.append(record)
        self._active[k] = record
        self._assigned.add(j)
        responses.append(
            dict(
                vehicle=k,
                task_id=j,
                accepted=True,
                planned_delivery_end=record["delivery_end"],
                pickup_point=record["pickup_point"],
            )
        )
    return responses


def _apply_replan(self, proposal):
    """Atomically replace feasible future suffixes, retain task ownership.

    Check full future paths and the already executed prefix independently.
    A rejected proposal leaves all environment state unchanged.
    """

    if not isinstance(proposal, dict) or not {
        "time",
        "before",
        "after",
        "trials",
        "plans",
        "records",
    } <= set(proposal):
        raise ValueError("Malformed replan proposal")
    if not isinstance(proposal["plans"], (list, tuple)) or not isinstance(
        proposal["records"], (list, tuple)
    ):
        raise ValueError("Malformed replan sequences")
    required_record = {
        "vehicle",
        "task_id",
        "assigned_at",
        "shelf",
        "pickup_point",
        "pickup_arrival",
        "pickup_end",
        "delivery_arrival",
        "delivery_end",
        "return_arrival",
        "return_end",
    }
    if any(
        record is not None and (not isinstance(record, dict) or not required_record <= set(record))
        for record in proposal["records"]
    ):
        raise ValueError("Malformed replan record")
    for path in proposal["plans"]:
        if (
            not isinstance(path, (list, tuple))
            or not path
            or any(
                not isinstance(q, (list, tuple))
                or len(q) != 2
                or any(type(x) is not int for x in q)
                for q in path
            )
        ):
            raise ValueError("Malformed replan path")
    for record in proposal["records"]:
        if record is not None:
            q = record.get("pickup_point") if isinstance(record, dict) else None
            if (
                not isinstance(q, (list, tuple))
                or len(q) != 2
                or any(type(x) is not int for x in q)
            ):
                raise ValueError("Malformed pickup point")
    metadata = {key: deepcopy(proposal[key]) for key in ("time", "before", "after", "trials")}
    trial = self.snapshot()
    if proposal["time"] != self.time:
        raise ValueError("Stale proposal")
    plans, records = proposal["plans"], proposal["records"]
    if len(plans) != len(self._plans) or len(records) != len(plans):
        raise ValueError("Missing vehicle suffix")
    changes = []
    for k, (path, new) in enumerate(zip(plans, records)):
        if not path or path[0] != self._plans[k][0] or path[-1] != self._scenario.homes[k]:
            raise ValueError("Invalid suffix endpoints")
        if (
            self._scenario.horizon is not None
            and self.time + len(path) - 1 > self._scenario.horizon
        ):
            raise ValueError("Suffix exceeds horizon")
        if any(
            not self._scenario.free(q) or q in set(self._scenario.homes) - {self._scenario.homes[k]}
            for q in path
        ):
            raise ValueError("Invalid suffix cell")
        if any(abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1 for a, b in zip(path, path[1:])):
            raise ValueError("Invalid suffix movement")
        old = self._active[k] or next(
            (r for r in reversed(self._records) if r["vehicle"] == k), None
        )
        if (old is None) != (new is None):
            raise ValueError("Task ownership changed")
        if old:
            if any(new[f] != old[f] for f in ("vehicle", "task_id", "assigned_at", "shelf")):
                raise ValueError("Task identity changed")
            for leg in ("pickup", "delivery"):
                if old[leg + "_arrival"] <= self.time:
                    if any(new[leg + f] != old[leg + f] for f in ("_arrival", "_end")):
                        raise ValueError("Started service changed")
                    if leg == "pickup" and new["pickup_point"] != old["pickup_point"]:
                        raise ValueError("Started pickup side changed")
            index = next(i for i, r in enumerate(trial._records) if r["task_id"] == old["task_id"])
            trial._records[index] = deepcopy(new)
            trial._active[k] = trial._records[index] if self._active[k] else None
            # Future service intervals must actually occupy their endpoints.
            job = self._jobs[new["task_id"]]
            for leg, point, duration in [
                ("pickup", new["pickup_point"], job.pickup_service),
                ("delivery", job.delivery, job.delivery_service),
            ]:
                a, b = new[leg + "_arrival"], new[leg + "_end"]
                if b - a != duration:
                    raise ValueError("Service duration changed")
                for t in range(max(a, self.time), b + 1):
                    if t - self.time >= len(path) or path[t - self.time] != point:
                        raise ValueError("Wrong future service")
        if path != self._plans[k]:
            changes.append(
                dict(
                    vehicle=k,
                    state=self._state(k),
                    task_id=old["task_id"] if old else None,
                    old_delivery_end=old["delivery_end"] if old else None,
                    new_delivery_end=new["delivery_end"] if new else None,
                    old_suffix=deepcopy(self._plans[k]),
                    new_suffix=deepcopy(path),
                )
            )
    for t in range(max(map(len, plans))):
        positions = [p[min(t, len(p) - 1)] for p in plans]
        if len(set(positions)) != len(plans):
            raise ValueError("Future vertex collision")
        if t:
            previous = [p[min(t - 1, len(p) - 1)] for p in plans]
            for k in range(len(plans)):
                for peer in range(k):
                    if previous[k] == positions[peer] and previous[peer] == positions[k]:
                        raise ValueError("Future edge swap")
    trial._plans = [Itinerary(path) for path in plans]
    # Independently validate past AND complete future execution, including
    # service order and metrics. This audit copy never dispatches new jobs.
    audit = trial.snapshot()
    remaining = max(map(len, plans)) - 1
    if remaining:
        audit.advance(remaining, observe=False)
    self.services.validate(audit._scenario, audit.result())

    old_records = [
        self._active[k] or next((r for r in reversed(self._records) if r["vehicle"] == k), None)
        for k in range(len(plans))
    ]
    before = self.services.suffix_score(self._plans, old_records, self.time)
    after = self.services.suffix_score(plans, records, self.time)
    if after >= before or tuple(metadata["before"]) != before or tuple(metadata["after"]) != after:
        raise ValueError("Candidate must improve the actual suffix objective")
    event = dict(**metadata, changes=changes)
    self._plans, self._records, self._active = trial._plans, trial._records, trial._active
    self._reservation_index = None
    self._replans.append(event)
    return True


def hold_return(env, vehicle, steps=1):
    """Atomically insert stationary steps before an uncommitted fallback return.

    Other vehicles retain their complete existing reservations, including their
    stationary final positions.  A collision, active service, or horizon
    violation rejects the hold without changing any environment state.
    """
    if (
        type(vehicle) is not int
        or not 0 <= vehicle < len(env._plans)
        or type(steps) is not int
        or steps < 1
    ):
        raise ValueError("Invalid standby vehicle or duration")
    if env._active[vehicle] is not None:
        raise ValueError("A committed task cannot be put on standby")
    if any(w["vehicle"] == vehicle and w["start"] <= env.time < w["end"] for w in env._idle_waits):
        raise ValueError("Standby already scheduled")
    scenario = env._scenario
    old_path = env._plans[vehicle]
    point = old_path[0]
    if not env.ruleset.may_wait_at(point):
        raise ValueError("Standby requires ordinary catalog transit floor")
    if len(old_path) <= 1:
        raise ValueError("No fallback return to hold")
    record_index = next(
        (i for i in range(len(env._records) - 1, -1, -1) if env._records[i]["vehicle"] == vehicle),
        None,
    )
    position_event = (
        next((r for r in reversed(env._position_events) if r["vehicle"] == vehicle), None)
        if env.positioning
        else None
    )
    if position_event is not None and any(
        r["vehicle"] == vehicle and r["assigned_at"] > position_event["start"] for r in env._records
    ):
        position_event = None
    if (
        record_index is not None
        and position_event is not None
        and env._records[record_index]["return_end"] <= position_event["start"]
    ):
        # Completed task history is immutable; a new empty trip owns its return.
        record_index = None
    shadow_return = getattr(env, "_visible_old_routes", {}).get(vehicle)
    if record_index is None and position_event is None and shadow_return is None:
        raise ValueError("No accepted task has a fallback return")
    latest = env._records[record_index] if record_index is not None else shadow_return
    old_end = env.time + len(old_path) - 1
    if latest is not None and (
        latest["delivery_end"] > env.time or latest["return_end"] != old_end
    ):
        raise ValueError("Fallback return metadata does not match current suffix")
    if scenario.horizon is not None and old_end + steps > scenario.horizon:
        raise ValueError("Standby exceeds supplied horizon")

    plans = list(env._plans)
    plans[vehicle] = [point] * steps + list(old_path)
    if env.plan_reservations().conflict(plans[vehicle], env.time, vehicle):
        raise ValueError("Standby conflicts with an existing route or edge swap")

    records = list(env._records)
    if record_index is not None:
        records[record_index] = deepcopy(latest)
        records[record_index]["return_end"] = old_end + steps
        records[record_index]["return_arrival"] = old_end + steps
    waits = [dict(w) for w in env._idle_waits]
    adjacent = next(
        (w for w in reversed(waits) if w["vehicle"] == vehicle and w["end"] == env.time),
        None,
    )
    if adjacent is None:
        waits.append(dict(vehicle=vehicle, start=env.time, end=env.time + steps))
    else:
        adjacent["end"] += steps
    env._replace_plan(vehicle, plans[vehicle], held_steps=steps)
    env._records, env._idle_waits = records, waits
    if position_event is not None:
        position_event["return_end"] = old_end + steps
    if record_index is None and shadow_return is not None:
        shadow_return.update(return_end=old_end + steps, return_arrival=old_end + steps)
    return dict(vehicle=vehicle, accepted=True, start=env.time, end=env.time + steps)


def reposition(env, vehicle, target):
    if not env.positioning or not env._scenario.is_v9_1:
        raise ValueError("Repositioning is an explicit V9.1 opt-in")
    if type(vehicle) is not int or not 0 <= vehicle < len(env._plans):
        raise ValueError("Unknown vehicle")
    if env._active[vehicle] is not None:
        raise ValueError("A committed task cannot be repositioned")
    if (
        not isinstance(target, (tuple, list))
        or len(target) != 2
        or any(type(x) is not int for x in target)
    ):
        raise ValueError("Target must contain two integer coordinates")
    target = tuple(target)
    scenario, now = env._scenario, env.time
    home = scenario.homes[vehicle]
    if target == home and env._plans[vehicle][0] == home:
        raise ValueError("Vehicle is already at home")
    if target != home and not env.ruleset.may_wait_at(target):
        raise ValueError("Positioning target must be ordinary transit floor or own home")
    if env.final_return_ready and target != home:
        raise ValueError("Final return cannot be replaced by positioning")
    vertices, edges = env.plan_reservations().view_excluding(vehicle, now)
    outward = env._router.leg(env._plans[vehicle][0], target, now, vehicle, vertices, edges)
    if outward is None:
        raise ValueError("No safe positioning route")
    arrival = now + len(outward) - 1
    back = env._router.leg(target, home, arrival, vehicle, vertices, edges)
    if back is None:
        raise ValueError("No safe fallback return")
    path = outward + back[1:]
    if env.plan_reservations().conflict(path, now, vehicle):
        raise ValueError("Positioning conflicts with an existing reservation")
    end = now + len(path) - 1
    records = list(env._records)
    index = next(
        (i for i in range(len(records) - 1, -1, -1) if records[i]["vehicle"] == vehicle), None
    )
    if index is not None and records[index]["return_end"] > now:
        records[index] = deepcopy(records[index])
        records[index].update(return_end=end, return_arrival=end)
    waits = [
        {**w, "end": min(w["end"], now)} if w["vehicle"] == vehicle else w for w in env._idle_waits
    ]
    event = dict(vehicle=vehicle, start=now, target=target, arrival=arrival, return_end=end)
    env._records = records
    env._idle_waits = [w for w in waits if w["start"] < w["end"]]
    env._replace_plan(vehicle, path)
    env._position_targets[vehicle] = (
        None if target == home else dict(target=target, arrival=arrival)
    )
    env._position_events = [
        e for e in env._position_events if not (e["vehicle"] == vehicle and e["start"] == now)
    ]
    env._position_events.append(event)
    return deepcopy(event)
