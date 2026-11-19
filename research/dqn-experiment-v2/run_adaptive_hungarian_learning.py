"""分阶段多轮训练/验证；test子命令只在检查点选择后运行一次未见日期对照。"""
import argparse
import json
import random
from pathlib import Path
from paths import ROOT,sha,verify_baseline
from adaptive_hungarian_learning import MultiStepAgent,execute,ADAPTATION,audit_adaptation

FOLDER=ROOT/'results/adaptive_hungarian_learning_v2'

def read(path): return json.loads(path.read_text(encoding='utf-8'))

def write(path,value):
    # 所有提交仅写入本实验目录，先完整写临时文件再原子替换，避免中断留下半条JSON。
    assert path.parent.resolve()==FOLDER.resolve()
    temporary=path.with_suffix(path.suffix+'.tmp')
    assert temporary.parent.resolve()==FOLDER.resolve()
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

def save(agent,path):
    assert path.parent.resolve()==FOLDER.resolve()
    temporary=path.with_suffix('.tmp')
    assert temporary.parent.resolve()==FOLDER.resolve()
    agent.save(temporary)
    temporary.replace(path)

def audit(row,case):
    audit_adaptation(row)
    assert row['valid'] and row['case']==case['case']
    f=.5*row['T']/900+.3*row['R']/900+.2*row['D']/5400
    assert abs(f-row['F'])<1e-10 and abs(row['reward_sum']+f)<1e-10
    assert abs(row['learning_reward_sum']-row['initial_cost']+f)<1e-10
    assert row['transitions'] and row['transitions'][-1]['done']
    assert sum(t['done'] for t in row['transitions'])==1
    assert sum(row['actions'].values())==len(row['transitions'])
    for t in row['transitions']:
        assert abs(sum(t['reward_terms'].values())-t['reward'])<1e-10 and t['duration']>=0

def record(path,row,case,**metadata):
    audit(row,case)
    row.update(metadata)
    write(path,row)
    print(json.dumps({k:v for k,v in row.items() if k not in ('transitions','losses','ga_searches')},ensure_ascii=False),flush=True)
    return row

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['fit','test'],default='fit')
    args=parser.parse_args()
    verify_baseline()
    protocol=read(ROOT/'data/adaptive_hungarian_learning_protocol.json')
    FOLDER.mkdir(parents=True,exist_ok=True)
    files=[ROOT/p for p in ('hungarian_learning.py','run_adaptive_hungarian_learning.py','adaptive_hungarian_learning.py','adaptive_genetic.py','create_adaptive_learning_variant.py','freeze_hungarian_learning.py',
        'prepare_hungarian_learning.py','data/adaptive_hungarian_learning_protocol.json','dqn_agent.py','dqn_policy.py','train_dqn.py','compare_dqn_controls.py')]
    files+=sorted((ROOT/'improved').glob('*.py'))
    identity={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    manifest=FOLDER/'manifest.json'
    if manifest.exists(): assert read(manifest)['hashes']==identity,'Frozen source drift'
    else: write(manifest,dict(hashes=identity,baseline_files=verify_baseline(),learning=protocol['learning'],action_definition=protocol['action_definition']))
    assert protocol['ga_adaptation']==ADAPTATION
    cases={c['case']:c for c in protocol['cases']}
    config=protocol['learning']
    if args.phase=='fit':
        # GA算子已变，必须重新运行GA；精准/匈牙利不调用GA，复用已审计的相同对照。
        old_manifest=read(ROOT/'results/hungarian_learning_v1/manifest.json')
        assert all(sha(ROOT/p)==digest for p,digest in old_manifest['hashes'].items())
        for index,name in enumerate(protocol['validation']):
            case=cases[name]
            for strategy in ('ga','exact','hungarian'):
                path=FOLDER/f'validation_control_{index:02d}_{strategy}.json'
                if path.exists(): audit(read(path),case); continue
                if strategy in ('exact','hungarian'):
                    source=ROOT/f'results/hungarian_learning_v1/validation_control_{index:02d}_{strategy}.json'
                    row=read(source)
                    assert row['strategy']==strategy and row['seed']==0
                    row.update(reused_from=source.relative_to(ROOT).as_posix(),reused_sha256=sha(source),ga_adaptation=ADAPTATION,ga_searches=[])
                else: row=execute(case,protocol,strategy=strategy)
                record(path,row,case,phase='validation_control',strategy=strategy,seed=0)
        agent=MultiStepAgent(seed=config['seed'],state_dim=32,hidden=config['hidden'],learning_rate=config['learning_rate'],
            gamma=1,double_dqn=True,output_scale=.01,capacity=20000,warmup=128)
        summaries=[]
        best_score=float('inf')
        for epoch in range(1,config['epochs']+1):
            order=list(protocol['development'])
            random.Random(config['seed']+epoch).shuffle(order)
            for index,name in enumerate(order):
                path=FOLDER/f'train_e{epoch:02d}_{index:02d}.json'
                checkpoint=FOLDER/f'train_e{epoch:02d}_{index:02d}.npz'
                if path.exists():
                    row=read(path); audit(row,cases[name])
                    assert row['checkpoint_sha256']==sha(checkpoint)
                    agent=MultiStepAgent.load(checkpoint)
                    continue
                agent.epsilon=max(.05,.40*.72**(epoch-1))
                row=execute(cases[name],protocol,agent,training=True)
                save(agent,checkpoint)
                record(path,row,cases[name],epoch=epoch,phase='train',strategy='dqn',seed=0,checkpoint_sha256=sha(checkpoint))
            epoch_path=FOLDER/f'epoch{epoch:02d}.npz'
            if not epoch_path.exists(): save(agent,epoch_path)
            assert sha(epoch_path)==sha(FOLDER/f'train_e{epoch:02d}_09.npz')
            ratios={strategy:[] for strategy in ('ga','exact','hungarian')}
            for index,name in enumerate(protocol['validation']):
                path=FOLDER/f'validation_e{epoch:02d}_{index:02d}.json'
                if path.exists(): row=read(path); audit(row,cases[name])
                else:
                    row=execute(cases[name],protocol,agent)
                    row=record(path,row,cases[name],epoch=epoch,phase='validation',strategy='dqn',seed=0,checkpoint_sha256=sha(epoch_path))
                assert row['checkpoint_sha256']==sha(epoch_path) and row['frozen_state_verified']
                for strategy in ratios:
                    control=read(FOLDER/f'validation_control_{index:02d}_{strategy}.json')
                    ratios[strategy].append(row['F']/control['F'])
            summary=dict(epoch=epoch,mean_ratios={k:sum(v)/len(v) for k,v in ratios.items()},checkpoint_sha256=sha(epoch_path),
                train_steps=agent.train_steps,replay_size=agent.replay_size)
            summary['selection_score']=max(summary['mean_ratios'].values())
            summaries.append(summary)
            if summary['selection_score']<best_score:
                best_score=summary['selection_score']
                save(agent,FOLDER/'best.npz')
                write(FOLDER/'selection.json',dict(**summary,checkpoint='best.npz',criterion=protocol['selection']))
            write(FOLDER/'learning_curve.json',summaries)
            print(json.dumps(dict(event='epoch_complete',**summary),ensure_ascii=False),flush=True)
        save(agent,FOLDER/'latest.npz')
        write(FOLDER/'fit_complete.json',dict(epochs=config['epochs'],latest_sha256=sha(FOLDER/'latest.npz'),
            best_sha256=sha(FOLDER/'best.npz'),selection_sha256=sha(FOLDER/'selection.json')))
        print('Initial six-epoch training and validation block complete; test remains unopened.',flush=True)
    else:
        complete=read(FOLDER/'fit_complete.json')
        curve=read(FOLDER/'learning_curve.json')
        assert complete['epochs']==config['epochs'] and [row['epoch'] for row in curve]==list(range(1,config['epochs']+1))
        assert complete['latest_sha256']==sha(FOLDER/'latest.npz')
        assert complete['best_sha256']==sha(FOLDER/'best.npz')
        assert complete['selection_sha256']==sha(FOLDER/'selection.json')
        selection=read(FOLDER/'selection.json')
        checkpoint=FOLDER/'best.npz'
        assert sha(checkpoint)==selection['checkpoint_sha256']
        # 测试身份写在首次执行前，恢复时拒绝更换模型后复用同一测试目录。
        lock=FOLDER/'test_lock.json'
        identity=dict(checkpoint_sha256=sha(checkpoint),protocol_sha256=sha(ROOT/'data/adaptive_hungarian_learning_protocol.json'))
        if lock.exists(): assert read(lock)==identity
        else: write(lock,identity)
        agent=MultiStepAgent.load(checkpoint)
        for index,name in enumerate(protocol['test']):
            for strategy in ('ga','exact','hungarian','dqn'):
                path=FOLDER/f'test_{index:02d}_{strategy}.json'
                if path.exists():
                    row=read(path); audit(row,cases[name])
                    assert row['strategy']==strategy and row['seed']==0 and row['phase']=='test'
                    assert row['checkpoint_sha256']==(sha(checkpoint) if strategy=='dqn' else None)
                    continue
                row=execute(cases[name],protocol,agent if strategy=='dqn' else None,strategy=strategy)
                record(path,row,cases[name],phase='test',strategy=strategy,seed=0,checkpoint_sha256=sha(checkpoint) if strategy=='dqn' else None)
        print('All five unseen dates and four paired strategies complete.',flush=True)

if __name__=='__main__': main()
