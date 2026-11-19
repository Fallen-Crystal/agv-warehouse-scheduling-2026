"""匈牙利/GA重新学习：独立适配器，不修改历史实验或物理执行代码。"""
from collections import Counter, deque
import copy
from statistics import mean, pstdev
from unittest.mock import patch
import numpy as np
from paths import ROOT
from dqn_agent import DQNAgent
from dqn_policy import DQNPolicy, ActionAdapter, enhanced_observation, physical_terms
from improved.policy import ResearchPolicy
from improved.hungarian import matching_hungarian
from compare_dqn_controls import FixedActionAgent
import train_dqn


class MultiStepAgent(DQNAgent):
    """gamma=1的5步Double DQN；每个新转移做4次经验回放更新。

    多步回报更快传播延迟收益。终局清空队列，故每个保存点均可精确续跑；
    回报仍是原始Phi差值之和，不改变正式F或人为奖励某种算法。
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.gamma != 1: raise ValueError('This multi-step implementation requires gamma=1')
        self.pending=deque()

    def remember(self,state,action,reward,next_state,done):
        self.pending.append((np.array(state,copy=True),action,float(reward),np.array(next_state,copy=True),bool(done)))
        if len(self.pending)>=5 or done:
            while self.pending:
                horizon=list(self.pending)[:5]
                first,last=horizon[0],horizon[-1]
                super().remember(first[0],first[1],sum(t[2] for t in horizon),last[3],last[4])
                self.pending.popleft()
                if not done: break

    def learn(self):
        losses=[super(MultiStepAgent,self).learn() for _ in range(4)]
        valid=[v for v in losses if v is not None]
        return mean(valid) if valid else None

    def save(self,path):
        if self.pending: raise ValueError('Save only after complete episodes')
        super().save(path)


def learning_observation(world,policy):
    """32维状态全部来自已发布订单；为一小时任务放宽旧时间截断。

    新增当前可用AGV到就绪订单的ETA统计，没有预览未来订单或运行GA探测。
    状态提供选择依据，最终动作仍完全由Q网络决定，不使用阈值门控。
    """
    state=enhanced_observation(world,policy)
    pending=[j for jid,j in world.visible.items() if jid not in world.assigned]
    ages=[max(0,world.time-j['release']) for j in pending]
    remaining=[max(0,r['end']-world.time) if r else 0 for r in world.active]
    moves=[sum(a!=b for a,b in zip(p,p[1:])) for p in world.plans]
    state[0]=len(pending)/(len(pending)+len(world.active))
    ready_count=len(world.ready())
    state[1]=ready_count/(ready_count+len(world.active))
    state[5]=max(ages,default=0)/(3600+max(ages,default=0))
    state[6]=world.time/(3600+world.time)
    state[10:14]=[min(mean(remaining)/3600,2),min(max(remaining,default=0)/3600,2),
                  min(mean(moves)/3600,2),min(max(moves,default=0)/3600,2)]
    free=[k for k,r in enumerate(world.active) if r is None]
    best=[min(world.estimate(k,j) for k in free) for j in world.ready()] if free else []
    best=[v for v in best if np.isfinite(v)]
    state += [min(len(pending)/64,4),min((mean(ages) if ages else 0)/3600,2),
              min(max(ages,default=0)/3600,2),min(min(best,default=0)/900,2),
              min((mean(best) if best else 0)/900,2),min(max(best,default=0)/900,2),
              min((pstdev(best) if best else 0)/900,2),len(free)/max(1,len(world.active))]
    return state


class LearningPolicy(DQNPolicy):
    """复用原转移与物理成本总账，仅扩展状态和动作0的实现。"""
    def __init__(self,seed,*,objective,agent,training):
        self.adapter=ActionAdapter()
        ResearchPolicy.__init__(self,'rl',seed,objective=objective,selector=self.adapter)
        self.agent,self.training=agent,training
        self.previous=None
        self.transitions=[]
        self.losses=[]
        self.action_counts=Counter()
        self.reward_sum=0.
        self.state_dim=32
        if agent.state_dim!=32: raise ValueError('Expected 32-dimensional new model')
        self.initial_cost=0.
        self.initial_cost_terms={}
        self.previous_terms=None
        self.previous_time=None

    def action(self,world):
        state=learning_observation(world,self)
        terms=physical_terms(world,self.objective)
        potential=sum(terms.values())
        self.transition(state,potential,False,terms=terms,time=world.time)
        action=self.agent.select(state,training=self.training)
        if self.previous is None:
            self.reward_sum=-potential
            self.initial_cost=potential
            self.initial_cost_terms=terms.copy()
        self.previous=(state,action,potential)
        self.previous_terms,self.previous_time=terms,world.time
        self.adapter.action=('matching','ga')[action]
        self.action_counts[('hungarian','ga')[action]]+=1
        return ResearchPolicy.action(self,world)

    def finish_episode(self,result):
        super().finish_episode(result)
        result['dqn']['observation_schema']='published-hour-v3-32'
        result['dqn']['action_definition']=['hungarian_f_surrogate','joint_ga']


def execute(case,protocol,agent=None,*,training=False,strategy='dqn',seed=0):
    """三个固定基线使用相同策略桥接与物理seed；纯GA允许复用原GA计划缓存。"""
    objective=train_dqn.LinearObjective(**protocol['objective'])
    if strategy=='exact':
        return train_dqn.execute(case,protocol,FixedActionAgent(0),seed,False)
    chosen=agent if strategy=='dqn' else FixedActionAgent(1 if strategy=='ga' else 0)
    before=copy.deepcopy(chosen) if strategy=='dqn' and not training else None
    with patch('improved.policy.matching',lambda world,scorer=None:matching_hungarian(world,objective)[0]):
        if strategy=='dqn':
            with patch('train_dqn.DQNPolicy',LearningPolicy):
                row=train_dqn.execute(case,protocol,chosen,seed,training)
        else:
            row=train_dqn.execute(case,protocol,chosen,seed,False)
    if before is not None:
        # 精确检查推断不改变配置、队列、随机源、参数、优化器与整个经验池。
        assert chosen.rng.bit_generator.state==before.rng.bit_generator.state
        assert (chosen.train_steps,chosen.replay.position,chosen.replay_size,chosen.epsilon)==(before.train_steps,before.replay.position,before.replay_size,before.epsilon)
        assert not chosen.pending and not before.pending
        for group in ('online','target','adam_m','adam_v'):
            for key in chosen._PARAMETERS: np.testing.assert_array_equal(getattr(chosen,group)[key],getattr(before,group)[key])
        for key in ('states','next_states','actions','rewards','dones'):
            np.testing.assert_array_equal(getattr(chosen.replay,key),getattr(before.replay,key))
        row['frozen_state_verified']=True
    return row
