"""任务执行环境。策略只使用 observe()，不能读取内部完整场景的未来任务。"""

from copy import deepcopy
from dataclasses import asdict

from agv.domain import Scenario
from agv.evaluation.diagnostics import summarize_failures
from agv.evaluation.metrics import summarize
from agv.planning import create_router
from agv.planning.pickup import plan_task
from agv.planning.reservations import VertexReservations
from agv.warehouse.rules import dispatch_status


class Environment:
    def __init__(
        self,
        scenario: Scenario,
        router_kind="astar",
        *,
        idle_hold_steps=0,
        stream_open=False,
        positioning=False,
    ):
        if type(idle_hold_steps) is not int or not 0 <= idle_hold_steps <= 1000:
            raise ValueError("idle_hold_steps must be an integer from 0 to 1000")
        if idle_hold_steps and not scenario.is_v9:
            raise ValueError("Bounded standby requires the explicit V9 catalog profile")
        if type(stream_open) is not bool:
            raise ValueError("stream_open must be boolean")
        if scenario.is_v9_1 and idle_hold_steps:
            raise ValueError("V9.1 uses stream standby, not a finite hold allowance")
        if type(positioning) is not bool or (positioning and not scenario.is_v9_1):
            raise ValueError("Positioning requires the explicit V9.1 profile")
        self.positioning = positioning
        self._manual_stream = stream_open
        self.idle_hold_steps = idle_hold_steps
        self._router_kind = router_kind
        self.reset(scenario)

    def reset(self, scenario=None):
        if scenario is not None:
            checked = deepcopy(scenario).check()
            if self.idle_hold_steps and not checked.is_v9:
                raise ValueError("Bounded standby requires the explicit V9 catalog profile")
            if self.idle_hold_steps and checked.is_v9_1:
                raise ValueError("V9.1 does not accept a finite hold allowance")
            if self.positioning and not checked.is_v9_1:
                raise ValueError("Positioning requires the explicit V9.1 profile")
            self._scenario = checked
        s = self._scenario
        self._public_map = s.observation_map()
        self.time = 0
        self._jobs = {j.id: j for j in s.tasks}
        self._router = create_router(self._router_kind, s)
        self._plans = [[p] for p in s.homes]  # 每个计划从当前time开始，终点为专属停车位
        self._paths = [[p] for p in s.homes]  # 实际执行轨迹
        self._interval_states = [[] for _ in s.homes]
        self._records = []
        self._idle_waits = []
        self._idle_hold_counts = [0] * len(s.homes)
        self._assigned = set()
        self._active = [None] * len(s.homes)
        self._planning_failures = []
        self._execution_error = None
        self._replans = []
        self._reservation_index = None
        self._position_targets = [None] * len(s.homes)
        self._position_events = []
        from agv.dispatch.order_stream import initialize

        initialize(self, self._manual_stream)
        return self.observe()

    def close_order_stream(self):
        """External publisher API; not a policy/dispatch action."""
        from agv.dispatch.order_stream import close

        close(self)

    def _state(self, k):
        r = self._active[k]
        t = self.time
        if r is None:
            if any(w["vehicle"] == k and w["start"] <= t < w["end"] for w in self._idle_waits):
                return "standby"
            return "returning" if len(self._plans[k]) > 1 else "idle"
        if t < r["pickup_arrival"]:
            return "to_pickup"
        if t < r["pickup_end"]:
            return "loading"
        if t < r["delivery_arrival"]:
            return "to_delivery"
        return "unloading"

    def observe(self):
        s = self._scenario
        # 不返回总任务数、未来release、生成种子或未来任务点。
        return deepcopy(
            dict(
                **(
                    dict(
                        idle_hold_steps=self.idle_hold_steps,
                        idle_hold_counts=list(self._idle_hold_counts),
                        idle_waits=deepcopy(self._idle_waits),
                    )
                    if s.is_v9
                    else {}
                ),
                **(
                    dict(
                        order_stream_closed=self._stream_closed,
                        stream_closed_at=self._stream_closed_at,
                        idle_policy="stream",
                        completed_flow_times=[
                            r["delivery_end"] - self._released_jobs[r["task_id"]].release
                            for r in self._records
                            if r["delivery_end"] <= self.time
                        ],
                    )
                    if s.is_v9_1
                    else {}
                ),
                time=self.time,
                **(
                    dict(positioning_targets=deepcopy(self._position_targets))
                    if self.positioning
                    else {}
                ),
                horizon=s.horizon,
                map=self._public_map,
                vehicles=[
                    dict(
                        id=k,
                        position=p[0],
                        state=self._state(k),
                        available=self._active[k] is None,
                        task_id=self._active[k]["task_id"] if self._active[k] else None,
                        committed_path=p if self._active[k] else [p[0]],
                        return_path=p if self._active[k] is None else [],
                        route_record=deepcopy(
                            self._active[k]
                            or next((r for r in reversed(self._records) if r["vehicle"] == k), None)
                        ),
                        active_task=asdict(self._jobs[self._active[k]["task_id"]])
                        if self._active[k]
                        else None,
                    )
                    for k, p in enumerate(self._plans)
                ],
                pending=[
                    dict(
                        **asdict(j),
                        dispatchable=dispatch_status(
                            s, j, self._records, self._assigned, self.time
                        )[0],
                        dispatch_block_reason=dispatch_status(
                            s, j, self._records, self._assigned, self.time
                        )[1],
                    )
                    for j in s.tasks
                    if j.release <= self.time and j.id not in self._assigned
                ],
                completed=[deepcopy(r) for r in self._records if r["delivery_end"] <= self.time],
            )
        )

    def assign(self, pairs):
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
            if not dispatch_status(
                self._scenario, self._jobs[j], self._records, self._assigned, self.time
            )[0]:
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
            vertices, edges = VertexReservations(), set()
            for other, plan in enumerate(self._plans):
                if other == k:
                    continue
                vertices.update((self.time + i, p) for i, p in enumerate(plan))
                edges.update((self.time + i, a, b) for i, (a, b) in enumerate(zip(plan, plan[1:])))
                # 每个尾点都是专属home，他车永远不可进入，故不展开无限尾部预约。
            job = self._jobs[j]
            # 不同相邻停靠格可独立装货；同格占用仍由车辆路径预约约束。
            path, record, failed, attempts = plan_task(
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
                e
                for e in self._position_events
                if not (e["vehicle"] == k and e["start"] == self.time)
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

    def _replace_plan(self, vehicle, path, *, held_steps=0):
        self._plans[vehicle] = path
        if self._reservation_index is not None:
            if held_steps:
                self._reservation_index.hold(vehicle, self.time, held_steps)
            else:
                self._reservation_index.replace(vehicle, path, self.time)

    def plan_reservations(self):
        from agv.planning.reservations import PlanReservations

        if self._reservation_index is None:
            self._reservation_index = PlanReservations(self._plans, self.time)
        return self._reservation_index

    def reposition(self, vehicle, target):
        """Replace an available car's uncommitted suffix, retaining a safe H return."""
        from agv.planning.reposition import reposition

        return reposition(self, vehicle, target)

    def apply_replan(self, proposal):
        """Atomically replace feasible future suffixes, retain task ownership.

        Check full future paths and the already executed prefix independently.
        A rejected proposal leaves all environment state unchanged.
        """
        from agv.evaluation.validation import validate

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
            record is not None
            and (not isinstance(record, dict) or not required_record <= set(record))
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
        trial = deepcopy(self)
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
                not self._scenario.free(q)
                or q in set(self._scenario.homes) - {self._scenario.homes[k]}
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
                index = next(
                    i for i, r in enumerate(trial._records) if r["task_id"] == old["task_id"]
                )
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
        trial._plans = deepcopy(plans)
        # Independently validate past AND complete future execution, including
        # service order and metrics. This audit copy never dispatches new jobs.
        audit = deepcopy(trial)
        remaining = max(map(len, plans)) - 1
        if remaining:
            audit.advance(remaining, observe=False)
        validate(audit._scenario, audit.result())
        from agv.planning.joint import score

        old_records = [
            self._active[k] or next((r for r in reversed(self._records) if r["vehicle"] == k), None)
            for k in range(len(plans))
        ]
        before = score(self._plans, old_records, self.time)
        after = score(plans, records, self.time)
        if (
            after >= before
            or tuple(metadata["before"]) != before
            or tuple(metadata["after"]) != after
        ):
            raise ValueError("Candidate must improve the actual suffix objective")
        event = dict(**metadata, changes=changes)
        self._plans, self._records, self._active = trial._plans, trial._records, trial._active
        self._reservation_index = None
        self._replans.append(event)
        return True

    def advance(self, steps=1, *, observe=True):
        if type(steps) is not int or steps < 1:
            raise ValueError("Invalid advance or horizon exceeded")
        if self._scenario.is_v9_1 and self.done:
            return self.observe() if observe else None
        if (
            type(steps) is not int
            or steps < 1
            or (self._scenario.horizon is not None and self.time + steps > self._scenario.horizon)
        ):
            raise ValueError("Invalid advance or horizon exceeded")
        for _ in range(steps):
            if self._scenario.is_v9_1 and self.done:
                break
            if self.idle_hold_steps or self._scenario.is_v9_1:
                from agv.dispatch.idle import advance_standby

                advance_standby(self)
            for k, plan in enumerate(self._plans):
                self._interval_states[k].append(self._state(k))
                if len(plan) > 1:
                    self._plans[k] = plan[1:]
                self._paths[k].append(self._plans[k][0])
            self.time += 1
            for k, r in enumerate(self._active):
                if r is not None and r["delivery_end"] <= self.time:
                    self._active[k] = None
            from agv.dispatch.order_stream import publish

            publish(self)
        return self.observe() if observe else None

    def stop_if_stalled(self, feedback):
        """Termination bookkeeping only; unreleased jobs never reach a policy."""
        if self._scenario.horizon is not None or self.done:
            return False
        if any(f["accepted"] for f in feedback) or any(len(p) > 1 for p in self._plans):
            return False
        if not self._stream_closed:
            return False
        self._execution_error = dict(
            kind="solver_stalled" if feedback else "policy_stalled",
            type="NoProgress",
            time=self.time,
            message="No active route, future release or accepted assignment; not proof of infeasibility",
        )
        return True

    @property
    def done(self):
        # 用于环境终止，不能用于提前获取未来任务数量。
        return (
            self._stream_closed
            and all(j in self._assigned for j in self._released_jobs)
            and all(r is None for r in self._active)
            and all(len(p) == 1 for p in self._plans)
            and all(p[0] == h for p, h in zip(self._plans, self._scenario.homes))
        )

    def result(self):
        records = [deepcopy(r) for r in self._records if r["delivery_end"] <= self.time]
        completions = [r["delivery_end"] for r in records]
        flow = [r["delivery_end"] - self._jobs[r["task_id"]].release for r in records]
        moves = service = idle = traffic_wait = 0
        for path, labels in zip(self._paths, self._interval_states):
            for a, b, state in zip(path, path[1:], labels):
                if a != b:
                    moves += 1
                elif state in ("loading", "unloading"):
                    service += 1
                elif state in ("idle", "standby"):
                    idle += 1
                else:
                    traffic_wait += 1
        result = dict(
            feasible=self.done,
            reason=None
            if self.done
            else ("horizon_exhausted" if self.time == self._scenario.horizon else "unfinished"),
            time=self.time,
            completed=len(records),
            total_tasks=len(self._jobs),
            makespan=max(completions, default=0),
            mean_completion=sum(completions) / len(records) if records else 0,
            mean_flow_time=sum(flow) / len(flow) if flow else 0,
            moves=moves,
            service_steps=service,
            idle_steps=idle,
            traffic_wait_steps=traffic_wait,
            paths=deepcopy(self._paths),
            interval_states=deepcopy(self._interval_states),
            events=records,
            assignments=deepcopy(self._records),
        )
        if self._scenario.is_v9_1:
            result.update(
                order_stream_closed=self._stream_closed,
                stream_closed_at=self._stream_closed_at,
                idle_policy="stream",
            )
            if self.positioning:
                result["positioning_events"] = deepcopy(self._position_events)
        if self._scenario.is_v9:
            result["idle_waits"] = deepcopy(self._idle_waits)
            result["idle_hold_steps"] = self.idle_hold_steps
        result["replanning_events"] = deepcopy(self._replans)
        result["routing_stats"] = deepcopy(self._router.stats)
        result.update(summarize(self._scenario, result))
        if self._execution_error:
            result["reason"] = self._execution_error["kind"]
        result["diagnostics"] = summarize_failures(
            self._scenario, result, deepcopy(self._planning_failures), self._execution_error
        )
        return result
