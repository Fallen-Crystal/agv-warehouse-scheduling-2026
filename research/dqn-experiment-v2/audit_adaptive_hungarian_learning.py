"""独立输入和训练产物审计；不执行策略，不以测试成绩选模型。"""
import bisect
import json
from collections import Counter
from paths import ROOT,sha,verify_baseline
from run_adaptive_hungarian_learning import FOLDER,read,write,audit
from adaptive_hungarian_learning import MultiStepAgent

def verify_inputs():
    protocol=read(ROOT/'data/adaptive_hungarian_learning_protocol.json')
    raw=ROOT/'deliverables/wepa_real_data/raw'
    assert sha(raw/'2_orders.json')==protocol['source_sha256']
    assert sha(raw/'3_initial_fill_lvl.json')==protocol['initial_stock_sha256']
    orders=read(raw/'2_orders.json')
    times=[r[2] for r in orders]
    assert times==sorted(times)
    cases={c['case']:c for c in protocol['cases']}
    groups={g:{cases[n]['source_day'] for n in protocol[g]} for g in ('development','validation','test')}
    assert groups['development'].isdisjoint(groups['validation'])
    assert groups['development'].isdisjoint(groups['test'])
    assert groups['validation'].isdisjoint(groups['test'])
    assert groups['test'].isdisjoint(protocol['previously_used_days'])
    assert set.union(*(set(protocol[g]) for g in groups))==set(cases)
    assert len(cases)==sum(len(protocol[g]) for g in groups)
    stock=Counter({int(k):v for k,v in read(raw/'3_initial_fill_lvl.json').items()})
    cursor=0
    source_rows=set()
    for case in sorted(cases.values(),key=lambda c:c['start_seconds']):
        start,end=case['start_seconds'],case['end_seconds']
        left,right=bisect.bisect_left(times,start),bisect.bisect_left(times,end)
        while cursor<left:
            row=orders[cursor]
            stock[row[1]]+=1 if row[0]=='delivery' else -1
            cursor+=1
        initial={int(k):v for k,v in case['initial'].items()}
        assert all(stock[s]==v for s,v in initial.items())
        assert [t['source_row'] for t in case['tasks']]==list(range(left,right))
        assert end-start==case['close_at'] in (1800,3600)
        assert case['source_day']==start//86400
        ledger=Counter(initial)
        for i,task in enumerate(case['tasks']):
            source=task['source_row']
            assert source not in source_rows
            source_rows.add(source)
            assert task['id']==i
            assert orders[source]==[task[k] for k in ('kind','sku','source_time','source_dock','batch','week')]
            assert 0<=task['release']==task['source_time']-start<case['close_at']
            ledger[task['sku']]+=1 if task['kind']=='delivery' else -1
            assert 0<=ledger[task['sku']]<=initial[task['sku']]+50
    return dict(valid=True,baseline_files=verify_baseline(),unique_orders=len(source_rows),
        days={k:sorted(v) for k,v in groups.items()},
        orders={k:sum(len(cases[n]['tasks']) for n in protocol[k]) for k in groups},
        source_rows_and_complete_batches_verified=True,initial_stock_and_capacity_prefix_verified=True,
        protocol_sha256=sha(ROOT/'data/adaptive_hungarian_learning_protocol.json'))


def analyze():
    protocol=read(ROOT/'data/adaptive_hungarian_learning_protocol.json')
    cases={c['case']:c for c in protocol['cases']}
    manifest=read(FOLDER/'manifest.json')
    assert all(sha(ROOT/p)==digest for p,digest in manifest['hashes'].items())
    assert verify_baseline()==manifest['baseline_files']
    import random
    import numpy as np
    config=protocol['learning']
    expected=[]
    for epoch in range(1,config['epochs']+1):
        order=list(protocol['development'])
        random.Random(config['seed']+epoch).shuffle(order)
        expected.extend((epoch,index,name) for index,name in enumerate(order))
    training=sorted(FOLDER.glob('train_e*_*.json'))
    decisions=steps=0
    for position,path in enumerate(training):
        epoch,index,name=expected[position]
        assert path.name==f'train_e{epoch:02d}_{index:02d}.json'
        row=read(path)
        audit(row,cases[name])
        assert row['epoch']==epoch and row['phase']=='train' and row['strategy']=='dqn' and row['seed']==0
        checkpoint=path.with_suffix('.npz')
        assert row['checkpoint_sha256']==sha(checkpoint)
        agent=MultiStepAgent.load(checkpoint)
        assert agent.state_dim==32 and agent.hidden==config['hidden'] and agent.double_dqn and agent.gamma==1
        assert agent.learning_rate==config['learning_rate']
        assert agent.epsilon==max(.05,.40*.72**(epoch-1)) and not agent.pending
        # 从原始逐决策奖励独立重建5步样本，核对检查点中的实际经验池。
        transitions=row['transitions']
        for offset,transition in enumerate(transitions):
            slot=(decisions+offset)%agent.capacity
            horizon=transitions[offset:offset+5]
            assert agent.replay.actions[slot]==transition['action']
            assert abs(agent.replay.rewards[slot]-sum(t['reward'] for t in horizon))<1e-10
            assert agent.replay.dones[slot]==horizon[-1]['done']
            if horizon[-1]['done']: np.testing.assert_array_equal(agent.replay.next_states[slot],np.zeros(32))
        decisions+=len(transitions)
        assert agent.replay_size==min(decisions,agent.capacity)
        assert agent.train_steps==row['train_steps'] and agent.train_steps>=steps
        assert agent.train_steps-steps==4*len(row['losses'])
        for group in ('online','target','adam_m','adam_v'):
            assert all(np.isfinite(v).all() for v in getattr(agent,group).values())
        steps=agent.train_steps
    validation=[]
    for epoch in range(1,config['epochs']+1):
        epoch_path=FOLDER/f'epoch{epoch:02d}.npz'
        if not epoch_path.exists(): break
        assert sha(epoch_path)==sha(FOLDER/f'train_e{epoch:02d}_09.npz')
        ratios={k:[] for k in ('ga','exact','hungarian')}
        for index,name in enumerate(protocol['validation']):
            path=FOLDER/f'validation_e{epoch:02d}_{index:02d}.json'
            if not path.exists(): break
            row=read(path); audit(row,cases[name])
            assert row['frozen_state_verified'] and not row['losses']
            assert row['checkpoint_sha256']==sha(epoch_path) and row['epoch']==epoch
            for strategy in ratios:
                control=read(FOLDER/f'validation_control_{index:02d}_{strategy}.json')
                audit(control,cases[name])
                assert control['strategy']==strategy and control['seed']==0
                if strategy in ('exact','hungarian'):
                    assert control['reused_sha256']==sha(ROOT/control['reused_from'])
                else: assert 'reused_from' not in control
                ratios[strategy].append(row['F']/control['F'])
        if len(ratios['ga'])<len(protocol['validation']): break
        means={k:sum(v)/len(v) for k,v in ratios.items()}
        validation.append(dict(epoch=epoch,mean_ratios=means,selection_score=max(means.values()),checkpoint_sha256=sha(epoch_path)))
    selection=read(FOLDER/'selection.json') if (FOLDER/'selection.json').exists() else None
    if validation:
        best=min(validation,key=lambda v:v['selection_score'])
        assert selection is not None
        for key in ('epoch','mean_ratios','selection_score','checkpoint_sha256'): assert selection[key]==best[key]
        assert sha(FOLDER/'best.npz')==best['checkpoint_sha256']
    fit_complete=(FOLDER/'fit_complete.json').exists()
    if fit_complete:
        complete=read(FOLDER/'fit_complete.json')
        assert len(training)==len(expected) and len(validation)==config['epochs']==complete['epochs']
        assert complete['latest_sha256']==sha(FOLDER/'latest.npz')
        assert complete['best_sha256']==sha(FOLDER/'best.npz')
        assert complete['selection_sha256']==sha(FOLDER/'selection.json')
    tests=[]
    for index,name in enumerate(protocol['test']):
        rows={}
        for strategy in ('ga','exact','hungarian','dqn'):
            path=FOLDER/f'test_{index:02d}_{strategy}.json'
            if not path.exists(): continue
            assert fit_complete, 'Test opened before fit completion'
            row=read(path); audit(row,cases[name])
            assert row['strategy']==strategy and row['seed']==0 and row['phase']=='test' and not row['losses']
            if strategy=='dqn':
                assert row['frozen_state_verified']
                assert row['checkpoint_sha256']==read(FOLDER/'test_lock.json')['checkpoint_sha256']==sha(FOLDER/'best.npz')
                assert set(row['actions'])<={'hungarian','ga'}
            elif strategy=='ga': assert row['actions'].get('matching',0)==0
            else: assert row['actions'].get('ga',0)==0
            rows[strategy]=row
        if len(rows)==4:
            tests.append(dict(case=name,day=cases[name]['source_day'],minutes=cases[name]['close_at']//60,
                orders=len(cases[name]['tasks']),F={k:v['F'] for k,v in rows.items()},
                actions=rows['dqn']['actions'],
                improvement_percent={k:100*(1-rows['dqn']['F']/rows[k]['F']) for k in ('ga','exact','hungarian')},
                physics={k:{field:v[field] for field in ('T','R','D','traffic_wait')} for k,v in rows.items()}))
    complete=fit_complete and len(tests)==len(protocol['test'])
    return dict(complete=complete,fit_complete=fit_complete,training_windows=len(training),training_decisions=decisions,train_steps=steps,
        validation_epochs=validation,completed_test_dates=len(tests),test=tests,
        mean_paired_improvement_percent={k:sum(t['improvement_percent'][k] for t in tests)/len(tests) for k in ('ga','exact','hungarian')} if tests else {},
        selection=selection)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--inputs',action='store_true'); args=parser.parse_args()
    result=verify_inputs() if args.inputs else analyze()
    FOLDER.mkdir(parents=True,exist_ok=True)
    write(FOLDER/('input_audit.json' if args.inputs else 'audit.json'),result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
