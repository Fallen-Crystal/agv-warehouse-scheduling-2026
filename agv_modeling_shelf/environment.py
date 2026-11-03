"""任务执行环境。策略只使用 observe()，不能读取内部完整场景的未来任务。"""
from copy import deepcopy
from dataclasses import asdict
import os
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
        self._task_views = {j.id: asdict(j) for j in s.tasks}
        # The map is immutable for the lifetime of an Environment.  Keep one
        # canonical, JSON-ready view instead of copying it on every observe().
        self._map_view = dict(width=s.width, height=s.height,
                              blocked=tuple(sorted(s.blocked)),
                              shelves=tuple(sorted(s.shelves)), homes=tuple(s.homes))
        self._router = Router(s)
        self._plans = [[p] for p in s.homes]  # 每个计划从当前time开始，终点为专属停车位
        self._paths = [[p] for p in s.homes]  # 实际执行轨迹
        self._interval_states = [[] for _ in s.homes]
        self._records = []
        self._assigned = set()
        self._active = [None]*len(s.homes)
        self._planning_failures=[]
        self._execution_error=None
        self._replans=[]
        # Paired with the incremental checks in apply_replan().  Enable in CI
        # (AGV_STRICT_REPLAN=1) to replay and independently validate every
        # accepted suffix against the full trajectory validator.
        self.strict_audit = os.environ.get('AGV_STRICT_REPLAN') == '1'
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
        # Only small dicts are copied; map/geometry and task definitions are
        # immutable tuples shared across observations.
        vehicles = []
        for k, p in enumerate(self._plans):
            active = self._active[k]
            record = active or next((r for r in reversed(self._records) if r['vehicle'] == k), None)
            vehicles.append(dict(
                id=k, position=p[0], state=self._state(k),
                available=active is None,
                task_id=active['task_id'] if active else None,
                committed_path=tuple(p) if active else (p[0],),
                return_path=tuple(p) if active is None else (),
                route_record=dict(record) if record is not None else None,
                active_task=dict(self._task_views[active['task_id']]) if active else None))
        return dict(time=self.time, horizon=s.horizon, map=dict(self._map_view),
                    vehicles=vehicles,
                    pending=[dict(self._task_views[j.id]) for j in s.tasks
                             if j.release <= self.time and j.id not in self._assigned],
                    completed=[dict(r) for r in self._records if r['delivery_end'] <= self.time])

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

    def apply_replan(self, proposal):
        """Atomically replace feasible future suffixes, retain task ownership.

        Only the not-yet-executed suffix is checked: the executed prefix was
        already accepted and is immutable.  This is equivalent to replaying the
        whole environment, but avoids the audit copy that dominated large-instance
        runtime.  A rejected proposal leaves every state field unchanged.
        """
        metadata={key:deepcopy(proposal[key]) for key in ('time','before','after','trials')}
        if proposal['time'] != self.time:
            raise ValueError('Stale proposal')
        plans, records = proposal['plans'], proposal['records']
        if len(plans) != len(self._plans) or len(records) != len(plans):
            raise ValueError('Missing vehicle suffix')
        homes = self._scenario.homes
        now = self.time
        new_records = list(self._records)
        new_active = list(self._active)
        old_records=[self._active[k] or next((r for r in reversed(self._records) if r['vehicle']==k),None)
                     for k in range(len(plans))]
        changes=[]
        for k, (path, new) in enumerate(zip(plans, records)):
            path = tuple(path)
            if not path or path[0] != self._plans[k][0] or path[-1] != homes[k]:
                raise ValueError('Invalid suffix endpoints')
            if now+len(path)-1 > self._scenario.horizon:
                raise ValueError('Suffix exceeds horizon')
            foreign = set(homes) - {homes[k]}
            if any(not self._scenario.free(q) or q in foreign for q in path):
                raise ValueError('Invalid suffix cell')
            if any(abs(a[0]-b[0])+abs(a[1]-b[1])>1 for a,b in zip(path,path[1:])):
                raise ValueError('Invalid suffix movement')
            old = old_records[k]
            if (old is None) != (new is None):
                raise ValueError('Task ownership changed')
            if old:
                if any(new[f] != old[f] for f in ('vehicle','task_id','assigned_at','shelf')):
                    raise ValueError('Task identity changed')
                for leg in ('pickup','delivery'):
                    if old[leg+'_arrival'] <= now:
                        if any(new[leg+f] != old[leg+f] for f in ('_arrival','_end')):
                            raise ValueError('Started service changed')
                        if leg=='pickup' and new['pickup_point'] != old['pickup_point']:
                            raise ValueError('Started pickup side changed')
                if self._active[k] is not None and new['delivery_end'] < now:
                    raise ValueError('Active task already completed')
                if not (new['assigned_at'] <= new['pickup_arrival'] <= new['pickup_end']
                        <= new['delivery_arrival'] <= new['delivery_end'] <= new['return_end']):
                    raise ValueError('Invalid task timing')
                if (self._active[k] is not None or len(path)>1) and new['return_end'] != now+len(path)-1:
                    raise ValueError('Wrong return end')
                job=self._jobs[new['task_id']]
                for leg, point, duration in [('pickup',new['pickup_point'],job.pickup_service),('delivery',job.delivery,job.delivery_service)]:
                    a,b=new[leg+'_arrival'],new[leg+'_end']
                    if b-a!=duration:
                        raise ValueError('Service duration changed')
                    for t in range(max(a,now),b+1):
                        if t-now>=len(path) or path[t-now]!=point:
                            raise ValueError('Wrong future service')
                index=next(i for i,r in enumerate(new_records) if r['task_id']==old['task_id'])
                new_records[index]=dict(new)
                new_active[k]=new_records[index] if self._active[k] is not None else None
            if path != tuple(self._plans[k]):
                changes.append(dict(vehicle=k, state=self._state(k),
                    task_id=old['task_id'] if old else None,
                    old_delivery_end=old['delivery_end'] if old else None,
                    new_delivery_end=new['delivery_end'] if new else None,
                    old_suffix=list(self._plans[k]), new_suffix=list(path)))
        max_len=max(map(len,plans))
        for t in range(max_len):
            positions=[p[min(t,len(p)-1)] for p in plans]
            if len(set(positions))!=len(positions):
                raise ValueError('Future vertex collision')
            if t:
                previous=[p[min(t-1,len(p)-1)] for p in plans]
                for a in range(len(plans)):
                    for b in range(a):
                        if previous[a]==positions[b] and previous[b]==positions[a]:
                            raise ValueError('Future edge swap')
        from joint_planning import score
        before=score(self._plans,old_records,now)
        after=score(plans,records,now)
        if after>=before or tuple(metadata['before'])!=before or tuple(metadata['after'])!=after:
            raise ValueError('Candidate must improve the actual suffix objective')
        event=dict(**metadata,changes=changes)
        if self.strict_audit:
            from validation import validate
            audit=deepcopy(self)
            audit._plans=[list(p) for p in plans]
            audit._records=[dict(r) if r is not None else None for r in new_records]
            audit._active=[dict(r) if r is not None else None for r in new_active]
            remaining=max(map(len,plans))-1
            if remaining:
                audit.advance(remaining)
            validate(audit._scenario,audit.result())
        self._plans=[list(p) for p in plans]
        self._records=new_records
        self._active=new_active
        self._replans.append(event)
        return True

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
        result['replanning_events']=deepcopy(self._replans)
        result.update(summarize(self._scenario, result))
        if self._execution_error:
            result['reason']=self._execution_error['kind']
        result['diagnostics']=summarize_failures(self._scenario,result,deepcopy(self._planning_failures),self._execution_error)
        return result
