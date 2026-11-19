"""只读训练检查点诊断：观察动作塌缩和数值尺度，不运行策略/访问未见输入。"""
import argparse
import json
import numpy as np
from paths import sha
from adaptive_hungarian_learning import MultiStepAgent
from run_adaptive_hungarian_learning import FOLDER,read,write


def summarize(agent,row):
    n=agent.replay_size
    if n==0: raise ValueError('No replay samples')
    # 环形池填满后按最早到最新排列；只访问已经落盘的真实训练状态。
    first=agent.replay.position if n==agent.capacity else 0
    slots=(first+np.arange(n))%agent.capacity
    states=agent.replay.states[slots]
    q,_,_=agent._forward(states,agent.online)
    greedy=q.argmax(axis=1)
    gap=q[:,1]-q[:,0]
    target=agent._bellman_targets(agent.replay.rewards[slots],agent.replay.next_states[slots],agent.replay.dones[slots])
    actions=agent.replay.actions[slots]
    residual=q[np.arange(n),actions]-target
    groups={}
    # 这些区间只用于描述训练状态，不参与策略决策，也不是手工门控。
    for label,mask in (
        ('pending_below_6',states[:,0]<.5),
        ('pending_6_to_23',(states[:,0]>=.5)&(states[:,0]<.8)),
        ('pending_at_least_24',states[:,0]>=.8)):
        count=int(mask.sum())
        groups[label]=dict(states=count,greedy_ga_fraction=float(greedy[mask].mean()) if count else None,
            mean_ga_minus_hungarian_Q=float(gap[mask].mean()) if count else None)
    transitions=row['transitions']
    count=len(transitions)
    assert count<=n
    episode_slots=(agent.replay.position-count+np.arange(count))%agent.capacity
    episode_q,_,_=agent._forward(agent.replay.states[episode_slots],agent.online)
    future_returns=np.cumsum([t['reward'] for t in transitions][::-1])[::-1]
    actual_actions=np.array([t['action'] for t in transitions],dtype=int)
    # 第20维是当前缓存计划存在标记；只作事后分组，不能当作性能收益证据。
    cache_groups={}
    for label,mask in (('absent',states[:,20]<.5),('present',states[:,20]>=.5)):
        size=int(mask.sum())
        cache_groups[label]=dict(states=size,greedy_ga_fraction=float(greedy[mask].mean()) if size else None,
            mean_ga_minus_hungarian_Q=float(gap[mask].mean()) if size else None)
    switches=int(np.count_nonzero(actual_actions[1:]!=actual_actions[:-1]))
    return dict(case=row['case'],epoch=row.get('epoch'),train_steps=agent.train_steps,replay_size=n,
        replay_behavior_actions={name:int((actions==action).sum()) for action,name in enumerate(('hungarian','ga'))},
        replay_state_greedy_actions={name:int((greedy==action).sum()) for action,name in enumerate(('hungarian','ga'))},
        ga_minus_hungarian_Q_quantiles={str(p):float(np.quantile(gap,p)) for p in (0,.1,.5,.9,1)},
        mean_abs_Q=float(np.abs(q).mean()),mean_abs_Q_gap=float(np.abs(gap).mean()),
        five_step_bellman_rmse=float(np.sqrt(np.mean(residual**2))),
        last_training_episode_behavior_return_rmse=float(np.sqrt(np.mean((episode_q[np.arange(count),actual_actions]-future_returns)**2))),
        backlog_groups=groups,cached_plan_groups=cache_groups,
        last_training_episode_action_switches=switches,
        last_training_episode_action_switch_fraction=switches/(count-1) if count>1 else None,
        interpretation='Diagnostics use historical training states only. Behavior-return error and action counts do not establish validation/test F improvement.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint-row',help='training JSON filename under this experiment; defaults to last committed episode')
    args=parser.parse_args()
    paths=sorted(FOLDER.glob('train_e*_*.json'))
    if args.checkpoint_row:
        path=(FOLDER/args.checkpoint_row).resolve()
        if path.parent!=FOLDER.resolve() or path.suffix!='.json': parser.error('row must be one JSON directly under this experiment')
    else:
        if not paths: parser.error('No training checkpoint has been committed yet')
        path=paths[-1]
    row=read(path)
    checkpoint=path.with_suffix('.npz')
    assert sha(checkpoint)==row['checkpoint_sha256']
    agent=MultiStepAgent.load(checkpoint)
    result=summarize(agent,row)
    result.update(checkpoint_sha256=sha(checkpoint),checkpoint_row=path.name)
    # 按检查点保留诊断，防止后续窗口覆盖早期动作分布与误差证据。
    write(FOLDER/f'diagnostics_{path.stem}.json',result)
    write(FOLDER/'training_diagnostics.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
