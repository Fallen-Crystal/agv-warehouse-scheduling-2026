"""Single execution kernel: policy-free state advancement and observation."""

from copy import deepcopy
from dataclasses import asdict

from agv.orders import OrderPublisher, ScheduledOrderSource
from agv.rules import get_ruleset
from agv.warehouse.scenarios import Scenario
from agv.world.commands import CommandGate, Hold, ReplaceSuffix, Reposition
from agv.world.itinerary import Itinerary
from agv.world.observation import Observation, freeze
from agv.world.reservations import ReservationTable
from agv.world.tasks import TaskBook


class WorldState:
    def __init__(
        self,
        scenario: Scenario,
        router_kind="astar",
        *,
        services,
        idle_hold_steps=0,
        stream_open=False,
        positioning=False,
    ):
        get_ruleset(scenario).validate_options(idle_hold_steps, stream_open, positioning)
        self.services = services
        self.gate = CommandGate()
        self.positioning = positioning
        self._manual_stream = stream_open
        self.idle_hold_steps = idle_hold_steps
        self._router_kind = router_kind
        self.reset(scenario)

    def reset(self, scenario=None):
        if scenario is not None:
            checked = deepcopy(scenario).check()
            get_ruleset(checked).validate_options(
                self.idle_hold_steps, self._manual_stream, self.positioning, reset=True
            )
            self._scenario = checked
        s = self._scenario
        self._public_map = freeze(s.observation_map())
        self.time = 0
        self.tasks = TaskBook({j.id: j for j in s.tasks}, [None] * len(s.homes))
        self._jobs = self.tasks.jobs
        self.ruleset = get_ruleset(s)
        self._router = self.services.router(self._router_kind, s)
        self._plans = [Itinerary([p]) for p in s.homes]  # 每个计划从当前time开始，终点为专属停车位
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
        self.orders = OrderPublisher(
            ScheduledOrderSource(tuple(s.tasks), s.order_stream_end), manual=self._manual_stream
        )
        self.orders.initialize()
        return self.observe()

    def close_order_stream(self):
        """External publisher API; not a policy/dispatch action."""
        self.orders.close(self.time)

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

    def _observation_data(self):
        s = self._scenario
        # 不返回总任务数、未来release、生成种子或未来任务点。
        return dict(
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
                    committed_path=list(p) if self._active[k] else [p[0]],
                    return_path=list(p) if self._active[k] is None else [],
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
            pending=self._pending_observations(),
            completed=[deepcopy(r) for r in self._records if r["delivery_end"] <= self.time],
        )

    def _replace_plan(self, vehicle, path, *, held_steps=0):
        self._plans[vehicle] = Itinerary(path)
        if self._reservation_index is not None:
            if held_steps:
                self._reservation_index.hold(vehicle, self.time, held_steps)
            else:
                self._reservation_index.replace(vehicle, path, self.time)

    def plan_reservations(self):
        if self._reservation_index is None:
            self._reservation_index = ReservationTable(self._plans, self.time)
        else:
            # Legacy callers may replace private list suffixes directly. New
            # commands always store Itinerary and update the index atomically.
            for vehicle, path in enumerate(self._plans):
                if not isinstance(path, Itinerary):
                    self._reservation_index.replace(vehicle, path, self.time)
        return self._reservation_index

    def advance(self, steps=1, *, observe=True):
        if type(steps) is not int or steps < 1:
            raise ValueError("Invalid advance or horizon exceeded")
        if self.ruleset.stream and self.done:
            return self.observe() if observe else None
        if (
            type(steps) is not int
            or steps < 1
            or (self._scenario.horizon is not None and self.time + steps > self._scenario.horizon)
        ):
            raise ValueError("Invalid advance or horizon exceeded")
        for _ in range(steps):
            if self.ruleset.stream and self.done:
                break
            for k, plan in enumerate(self._plans):
                self._interval_states[k].append(self._state(k))
                if len(plan) > 1:
                    self._plans[k] = (
                        plan.advance() if isinstance(plan, Itinerary) else Itinerary(plan, 1)
                    )
                self._paths[k].append(self._plans[k][0])
            self.time += 1
            for k, r in enumerate(self._active):
                if r is not None and r["delivery_end"] <= self.time:
                    self._active[k] = None
            self.orders.publish(self.time)
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
        return self.ruleset.termination(self._plans, self._assigned, self._active, self.orders)

    def result(self):
        return self.services.result_builder(self._scenario, self.export_trace())

    def export_trace(self):
        """Detached events/positions; never expose the mutable kernel to metrics."""
        return deepcopy(
            dict(
                time=self.time,
                done=self.done,
                records=self._records,
                jobs=self._jobs,
                paths=self._paths,
                interval_states=self._interval_states,
                stream_closed=self._stream_closed,
                stream_closed_at=self._stream_closed_at,
                position_events=self._position_events,
                positioning=self.positioning,
                idle_waits=self._idle_waits,
                idle_hold_steps=self.idle_hold_steps,
                replans=self._replans,
                execution_error=self._execution_error,
                planning_failures=self._planning_failures,
                routing_stats=self._router.stats,
            )
        )

    def assign(self, pairs):
        return self.gate.assign(self, pairs)

    def reposition(self, vehicle, target):
        return self.gate.apply(self, [Reposition(vehicle, target)])

    def hold(self, vehicle, steps=1, *, counted=False):
        result = self.gate.apply(self, [Hold(vehicle, steps)])
        if counted:
            self._idle_hold_counts[vehicle] += 1
        return result

    def apply_replan(self, proposal):
        return self.gate.apply(self, [ReplaceSuffix(proposal)])

    def record_execution_error(self, kind, error):
        self._execution_error = dict(
            kind=kind, type=type(error).__name__, message=str(error), time=self.time
        )

    def snapshot(self):
        # Geometry is private and never mutated by commands. State and router
        # counters are detached; sharing geometry avoids copying a whole map.
        memo = {id(self._scenario): self._scenario, id(self._public_map): self._public_map}
        memo.update((id(path), path) for path in self._plans if isinstance(path, Itinerary))
        return deepcopy(self, memo)

    @property
    def final_return_ready(self):
        return (
            self._stream_closed
            and all(j in self._assigned for j in self._released_jobs)
            and all(r is None for r in self._active)
        )

    def tick(self, steps=1, *, observe=True):
        return WorldState.advance(self, steps, observe=observe)

    def clear_position_target(self, vehicle):
        self._position_targets[vehicle] = None

    @property
    def _released_jobs(self):
        return self.orders._released_jobs

    @_released_jobs.setter
    def _released_jobs(self, value):
        self.orders._released_jobs = value

    @property
    def _stream_closed(self):
        return self.orders.closed

    @_stream_closed.setter
    def _stream_closed(self, value):
        self.orders.closed = value

    @property
    def _stream_closed_at(self):
        return self.orders.closed_at

    @_stream_closed_at.setter
    def _stream_closed_at(self, value):
        self.orders.closed_at = value

    def _pending_observations(self):
        pending = []
        for job in self._scenario.tasks:
            if job.release <= self.time and job.id not in self._assigned:
                allowed, reason = self.ruleset.dispatchable(
                    job, self._records, self._assigned, self.time
                )
                pending.append(
                    dict(**asdict(job), dispatchable=allowed, dispatch_block_reason=reason)
                )
        return pending

    def observe(self):
        """Historical mutable/detached JSON observation."""
        return deepcopy(self._observation_data())

    def observe_view(self):
        """Immutable observation for the runner; geometry is shared once."""
        return Observation(freeze(self._observation_data()))

    @property
    def _jobs(self):
        return self.tasks.jobs

    @_jobs.setter
    def _jobs(self, value):
        self.tasks.jobs = value
        self.__dict__["_jobs"] = value

    @property
    def _assigned(self):
        return self.tasks.assigned

    @_assigned.setter
    def _assigned(self, value):
        self.tasks.assigned = value
        self.__dict__["_assigned"] = value

    @property
    def _active(self):
        return self.tasks.active

    @_active.setter
    def _active(self, value):
        self.tasks.active = value
        self.__dict__["_active"] = value

    @property
    def _records(self):
        return self.tasks.records

    @_records.setter
    def _records(self, value):
        self.tasks.records = value
        self.__dict__["_records"] = value
