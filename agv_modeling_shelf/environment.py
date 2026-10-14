"""任务执行环境。策略只使用 observe()，不能读取内部完整场景的未来任务。"""
from copy import deepcopy
from dataclasses import asdict
from model import Scenario
from routing import Router
from metrics import summarize
from diagnostics import summarize_failures
from pickup_planning import plan_task


class Environment:
    def __init__(self, scenario: Scenario):
        self.reset(scenario)

    def reset(self, scenario=None):
        if scenario is not None:
            self._scenario = deepcopy(scenario).check()
        s = self._scenario
        self.time = 0
        self._jobs = {j.id: j for j in s.tasks}
        self._router = Router(s)
        self._plans = [[p] for p in s.homes]  # 每个计划从当前time开始，终点为专属停车位
        self._paths = [[p] for p in s.homes]  # 实际执行轨迹
        self._interval_states = [[] for _ in s.homes]
        self._records = []
        self._assigned = set()
        self._active = [None]*len(s.homes)
        self._planning_failures=[]
        self._execution_error=None
        return self.observe()

    def _state(self, k):
        r = self._active[k]
        t = self.time
        if r is None:
            return 'returning' if len(self._plans[k]) > 1 else 'idle'
        if t < r['pickup_arrival']:
            return 'to_pickup'
        if t < r['pickup_end']:
            return 'loading'
        if t < r['delivery_arrival']:
            return 'to_delivery'
        return 'unloading'

    def observe(self):
        s = self._scenario
        # 不返回总任务数、未来release、生成种子或未来任务点。
        return deepcopy(dict(time=self.time, horizon=s.horizon,
            map=dict(width=s.width, height=s.height, blocked=sorted(s.blocked),
                     shelves=sorted(s.shelves), homes=s.homes),
            vehicles=[dict(id=k, position=p[0], state=self._state(k),
                           available=self._active[k] is None,
                           task_id=self._active[k]['task_id'] if self._active[k] else None,
                           committed_path=p if self._active[k] else [p[0]],
                           return_path=p if self._active[k] is None else [])
                      for k, p in enumerate(self._plans)],
            pending=[asdict(j) for j in s.tasks if j.release <= self.time and j.id not in self._assigned],
            completed=[deepcopy(r) for r in self._records if r['delivery_end'] <= self.time]))

    def assign(self, pairs):
        """有序(vehicle_id,task_id)列表。非法输入整批拒绝；规划失败逐对报告。

        每辆车/任务每批最多出现一次。合法批次按输入顺序预约，先提交者优先。
        已取货任务不可取消；本版本从指派成功开始锁定到卸货结束。
        """
        pairs = list(pairs)
        ks, js = [], []
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError('Expected (vehicle_id, task_id)')
            k, j = pair
            if type(k) is not int or not 0 <= k < len(self._plans) or self._active[k] is not None:
                raise ValueError('Unknown or busy vehicle')
            if type(j) is not int or j not in self._jobs or j in self._assigned or self._jobs[j].release > self.time:
                raise ValueError('Unknown, assigned or unreleased task')
            ks.append(k); js.append(j)
        if len(set(ks)) != len(ks) or len(set(js)) != len(js):
            raise ValueError('Duplicate vehicle or task in batch')
        responses = []
        for k, j in pairs:
            vertices, edges = set(), set()
            for other, plan in enumerate(self._plans):
                if other == k:
                    continue
                vertices.update((self.time+i, p) for i, p in enumerate(plan))
                edges.update((self.time+i, a, b) for i, (a, b) in enumerate(zip(plan, plan[1:])))
                # 每个尾点都是专属home，他车永远不可进入，故不展开无限尾部预约。
            job = self._jobs[j]
            # 不同相邻停靠格可独立装货；同格占用仍由车辆路径预约约束。
            path,record,failed,attempts=plan_task(self._scenario,self._router,job,k,self._plans[k][0],self.time,vertices,edges)
            if failed:
                self._planning_failures.append(dict(time=self.time,vehicle=k,task_id=j,
                    failed_leg=failed,reason='no_route_within_horizon',candidate_attempts=attempts))
                responses.append(dict(vehicle=k, task_id=j, accepted=False,
                    reason='no_route_within_horizon', failed_leg=failed))
                continue
            self._plans[k] = path
            self._records.append(record)
            self._active[k] = record
            self._assigned.add(j)
            responses.append(dict(vehicle=k, task_id=j, accepted=True,
                                  planned_delivery_end=record['delivery_end'],pickup_point=record['pickup_point']))
        return responses

    def advance(self, steps=1):
        if type(steps) is not int or steps < 1 or self.time+steps > self._scenario.horizon:
            raise ValueError('Invalid advance or horizon exceeded')
        for _ in range(steps):
            for k, plan in enumerate(self._plans):
                self._interval_states[k].append(self._state(k))
                if len(plan) > 1:
                    self._plans[k] = plan[1:]
                self._paths[k].append(self._plans[k][0])
            self.time += 1
            for k, r in enumerate(self._active):
                if r is not None and r['delivery_end'] <= self.time:
                    self._active[k] = None
        return self.observe()

    @property
    def done(self):
        # 用于环境终止，不能用于提前获取未来任务数量。
        return len(self._assigned) == len(self._jobs) and all(r is None for r in self._active) and all(len(p) == 1 for p in self._plans)

    def result(self):
        records = [deepcopy(r) for r in self._records if r['delivery_end'] <= self.time]
        completions = [r['delivery_end'] for r in records]
        flow = [r['delivery_end']-self._jobs[r['task_id']].release for r in records]
        moves = service = idle = traffic_wait = 0
        for path, labels in zip(self._paths, self._interval_states):
            for a, b, state in zip(path, path[1:], labels):
                if a != b:
                    moves += 1
                elif state in ('loading', 'unloading'):
                    service += 1
                elif state == 'idle':
                    idle += 1
                else:
                    traffic_wait += 1
        result = dict(feasible=self.done, reason=None if self.done else ('horizon_exhausted' if self.time == self._scenario.horizon else 'unfinished'),
            time=self.time, completed=len(records), total_tasks=len(self._jobs),
            makespan=max(completions, default=0), mean_completion=sum(completions)/len(records) if records else 0,
            mean_flow_time=sum(flow)/len(flow) if flow else 0,
            moves=moves, service_steps=service, idle_steps=idle, traffic_wait_steps=traffic_wait,
            paths=deepcopy(self._paths), interval_states=deepcopy(self._interval_states),
            events=records, assignments=deepcopy(self._records))
        result.update(summarize(self._scenario, result))
        if self._execution_error:
            result['reason']=self._execution_error['kind']
        result['diagnostics']=summarize_failures(self._scenario,result,deepcopy(self._planning_failures),self._execution_error)
        return result
