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
    def __init__(self, scenario: Scenario, router_kind="astar"):
        self._router_kind = router_kind
        self.reset(scenario)

    def reset(self, scenario=None):
        if scenario is not None:
            self._scenario = deepcopy(scenario).check()
        s = self._scenario
        self.time = 0
        self._jobs = {j.id: j for j in s.tasks}
        self._router = create_router(self._router_kind, s)
        self._plans = [[p] for p in s.homes]  # 每个计划从当前time开始，终点为专属停车位
        self._paths = [[p] for p in s.homes]  # 实际执行轨迹
        self._interval_states = [[] for _ in s.homes]
        self._records = []
        self._assigned = set()
        self._active = [None] * len(s.homes)
        self._planning_failures = []
        self._execution_error = None
        self._replans = []
        return self.observe()

    def _state(self, k):
        r = self._active[k]
        t = self.time
        if r is None:
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
                time=self.time,
                horizon=s.horizon,
                map=s.observation_map(),
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
        ks, js = [], []
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("Expected (vehicle_id, task_id)")
            k, j = pair
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
            ks.append(k)
            js.append(j)
        if len(set(ks)) != len(ks) or len(set(js)) != len(js):
            raise ValueError("Duplicate vehicle or task in batch")
        if self._scenario.is_v4 and len({self._jobs[j].shelf for j in js}) != len(js):
            raise ValueError("Only one order per shelf face per dispatch batch")
        responses = []
        for k, j in pairs:
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
                self._scenario, self._router, job, k, self._plans[k][0], self.time, vertices, edges
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
            self._plans[k] = path
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

    def apply_replan(self, proposal):
        """Atomically replace feasible future suffixes, retain task ownership.

        Check full future paths and the already executed prefix independently.
        A rejected proposal leaves all environment state unchanged.
        """
        from agv.evaluation.validation import validate

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
        self._replans.append(event)
        return True

    def advance(self, steps=1, *, observe=True):
        if (
            type(steps) is not int
            or steps < 1
            or (self._scenario.horizon is not None and self.time + steps > self._scenario.horizon)
        ):
            raise ValueError("Invalid advance or horizon exceeded")
        for _ in range(steps):
            for k, plan in enumerate(self._plans):
                self._interval_states[k].append(self._state(k))
                if len(plan) > 1:
                    self._plans[k] = plan[1:]
                self._paths[k].append(self._plans[k][0])
            self.time += 1
            for k, r in enumerate(self._active):
                if r is not None and r["delivery_end"] <= self.time:
                    self._active[k] = None
        return self.observe() if observe else None

    def stop_if_stalled(self, feedback):
        """Termination bookkeeping only; unreleased jobs never reach a policy."""
        if self._scenario.horizon is not None or self.done:
            return False
        if any(f["accepted"] for f in feedback) or any(len(p) > 1 for p in self._plans):
            return False
        if any(j.release > self.time for j in self._jobs.values()):
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
            len(self._assigned) == len(self._jobs)
            and all(r is None for r in self._active)
            and all(len(p) == 1 for p in self._plans)
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
                elif state == "idle":
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
        result["replanning_events"] = deepcopy(self._replans)
        result["routing_stats"] = deepcopy(self._router.stats)
        result.update(summarize(self._scenario, result))
        if self._execution_error:
            result["reason"] = self._execution_error["kind"]
        result["diagnostics"] = summarize_failures(
            self._scenario, result, deepcopy(self._planning_failures), self._execution_error
        )
        return result
