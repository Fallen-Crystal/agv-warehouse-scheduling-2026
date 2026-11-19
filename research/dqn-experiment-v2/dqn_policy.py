"""DQN与冻结仿真间的桥接：逐决策转移，不改变物理执行规则。"""
from collections import Counter
from improved.policy import ResearchPolicy


STATE_DIM_V2 = 24


def enhanced_observation(world, policy=None):
    """24维v2状态：只用已发布信息、已提交路线和当前GA缓存。

    保留旧10维作为前缀；计划剩余距离是已提交路线，不预览未来订单。
    汇总统计仍是部分观测，不能宣称恢复完整Markov状态。
    """
    state = observation(world)
    count = max(1, len(world.active))
    remaining = [max(0, r['end']-world.time) if r else 0 for r in world.active]
    moves = [sum(a != b for a,b in zip(p,p[1:])) for p in world.plans]
    width, height = max(1,world.scene.width-1), max(1,world.scene.height-1)
    positions = [p[0] for p in world.plans]
    xs, ys = [p[0]/width for p in positions], [p[1]/height for p in positions]
    pending = [j for jid,j in world.visible.items() if jid not in world.assigned]
    ports = [j['port'] for j in pending]
    plan = getattr(policy,'plan',None)
    ready_ids = {j['id'] for j in world.ready()}
    cached_ids = set(plan[0]) if plan is not None else set()
    state += [min(sum(remaining)/count/900,1),min(max(remaining,default=0)/900,1),
              min(sum(moves)/count/900,1),min(max(moves,default=0)/900,1),
              sum(xs)/count,sum(ys)/count,max(xs,default=0)-min(xs,default=0),
              max(ys,default=0)-min(ys,default=0),
              sum(p[0]/width for p in ports)/max(1,len(ports)),
              sum(p[1]/height for p in ports)/max(1,len(ports)),
              float(plan is not None),len(ready_ids & cached_ids)/max(1,len(ready_ids)),
              min(max(0,world.time-getattr(policy,'last_search',world.time))/900,1) if plan is not None else 0,
              sum(jid not in world.completed for jid in world.visible)/max(1,len(world.visible))]
    return state


def observation(world):
    """只观察已发布订单与当前物理状态，不读取未来订单的属性。"""
    vehicles = max(1, len(world.active))
    pending = [j for jid,j in world.visible.items() if jid not in world.assigned]
    ready = world.ready()
    stationary = moving_ticks = 0
    for path, labels in zip(world.history, world.labels):
        for a,b,label in list(zip(path,path[1:],labels))[-32:]:
            if label in ("empty", "loaded"):
                moving_ticks += 1
                stationary += a == b
    age = max((world.time-j["release"] for j in pending),default=0)
    return [min(2.0,len(pending)/vehicles)/2,
            min(2.0,len(ready)/vehicles)/2,
            sum(a is not None for a in world.active)/vehicles,
            stationary/max(1,moving_ticks),
            len(world.stock)/max(1,len(world.slots)),
            min(age/900,2)/2, min(world.time/900,3)/3,
            len(world.completed)/max(1,len(world.visible)),
            sum(j["kind"]=="retrieval" for j in ready)/max(1,len(ready)),
            len(pending)/max(1,len(world.visible))]


def physical_terms(world, objective):
    """累计物理成本Phi；终局恰好等于正式F。

    每秒未完成订单累积等待/服务流时间；尚未发布订单贡献0。
    T在最后任务完成后停止增长，D继续累计最终返库路程。
    N仅用于奖励的固定归一化，不作为未来订单属性输入网络。
    """
    completed_end = {r["task"]:r["end"] for r in world.records
                     if r["task"] in world.completed}
    t = max(completed_end.values(),default=0) if len(world.completed)==len(world.tasks) else world.time
    flow = sum(completed_end[jid]-j["release"] if jid in completed_end
               else world.time-j["release"] for jid,j in world.visible.items())
    return dict(zip(('T','R','D'),objective.terms((t,flow/max(1,len(world.tasks)),world.past_moves))))


def physical_potential(world, objective):
    return sum(physical_terms(world,objective).values())


class ActionAdapter:
    """沿用既有RL分支，动作由DQN给定，而不是阈值规则。"""
    def __init__(self):
        self.logs = []
        self.action = "matching"
    def choose(self, state, *, idle, ready):
        return self.action if idle > 0 and ready > 0 else "wait"
    def edge_score(self, *, distance, wait=0.0, inventory_risk=0.0):
        return -(float(distance)+.25*float(wait)+.5*float(inventory_risk))


class DQNPolicy(ResearchPolicy):
    def __init__(self, seed, *, objective, agent, training):
        self.adapter = ActionAdapter()
        super().__init__("rl",seed,objective=objective,selector=self.adapter)
        self.agent, self.training = agent, training
        self.previous = None
        self.transitions = []
        self.losses = []
        self.action_counts = Counter()
        self.reward_sum = 0.0
        self.state_dim = getattr(agent,'state_dim',10)
        if self.state_dim not in (10,STATE_DIM_V2):
            raise ValueError('Unsupported observation schema')
        self.initial_cost = 0.0
        self.initial_cost_terms = {}
        self.previous_terms = None
        self.previous_time = None

    def transition(self, state, potential, done, *, terms=None, time=None):
        if self.previous is None:
            return
        old_state, action, old_potential = self.previous
        reward = old_potential-potential
        self.reward_sum += reward
        item = (old_state,action,reward,state,done)
        record = dict(action=action,reward=reward,done=done)
        if terms is not None and self.previous_terms is not None:
            record['reward_terms'] = {k:self.previous_terms[k]-terms[k] for k in ('T','R','D')}
            record['duration'] = time-self.previous_time
        self.transitions.append(record)
        if self.training:
            self.agent.remember(*item)
            loss = self.agent.learn()
            if loss is not None:
                self.losses.append(float(loss))

    def action(self, world):
        state = enhanced_observation(world,self) if self.state_dim==STATE_DIM_V2 else observation(world)
        terms = physical_terms(world,self.objective)
        potential = sum(terms.values())
        self.transition(state,potential,False,terms=terms,time=world.time)
        action = self.agent.select(state,training=self.training)
        # 首个决策之前为无控制的时间段；计入奖励保证总和=-F。
        if self.previous is None:
            self.reward_sum = -potential
            self.initial_cost = potential
            self.initial_cost_terms = terms.copy()
        self.previous = (state,action,potential)
        self.previous_terms, self.previous_time = terms, world.time
        self.adapter.action = ("matching","ga")[action]
        self.action_counts[self.adapter.action] += 1
        return super().action(world)

    def finish_episode(self, result):
        if not result["valid"]:
            raise ValueError("Incomplete episode; do not issue successful terminal reward")
        terms = dict(zip(('T','R','D'),self.objective.terms(tuple(result[k] for k in ('T','R','D'))))) if all(k in result for k in ('T','R','D')) else None
        self.transition([0.0]*self.state_dim,result["objective_value"],True,
                        terms=terms,time=result.get('time'))
        self.previous = None
        # 暴露可审计学习信息，不复制整个经验池到轨迹文件。
        result["dqn"] = dict(actions=dict(self.action_counts),
                             transitions=self.transitions, losses=self.losses,
                             reward_sum=self.reward_sum,initial_cost=self.initial_cost,
                             initial_cost_terms=self.initial_cost_terms,
                             learning_reward_sum=sum(t['reward'] for t in self.transitions),
                             observation_schema='published-v2-24' if self.state_dim==STATE_DIM_V2 else 'published-v1-10',
                             train_steps=self.agent.train_steps)
