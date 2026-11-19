"""加载已选DQN，在用户提供的新案例上冻结推断；不会调用任何训练方法。"""
import argparse
from collections import Counter
import json
from pathlib import Path
from paths import ROOT,sha,verify_baseline
from adaptive_hungarian_learning import MultiStepAgent,execute
from run_adaptive_hungarian_learning import FOLDER,read,audit


def validate_case(case):
    """先验证基本账本；物理可执行性仍由原build与轨迹校验决定。"""
    if not isinstance(case,dict): raise ValueError('case must be a JSON object')
    if not isinstance(case.get('case'),str) or not case['case'].strip():
        raise ValueError('case must be a nonempty name')
    close=case.get('close_at')
    if type(close) is not int or close<=0:
        raise ValueError('close_at must be a positive integer in seconds')
    raw_initial=case.get('initial')
    if not isinstance(raw_initial,dict) or not raw_initial:
        raise ValueError('initial stock must be a nonempty object keyed by integer SKU')
    initial={}
    for key,count in raw_initial.items():
        # JSON对象键是字符串；内部调用也允许int，但不能截断浮点SKU或接受bool。
        if type(key) not in (str,int): raise ValueError('initial SKU keys must be integers')
        try: sku=int(key)
        except (ValueError,TypeError): raise ValueError('initial SKU keys must be integers') from None
        if sku in initial: raise ValueError('initial SKU keys collide after integer normalization')
        initial[sku]=count
    if any(type(v) is not int or v<0 for v in initial.values()):
        raise ValueError('initial stock must contain nonnegative integer counts')
    tasks=case.get('tasks')
    if not isinstance(tasks,list) or not tasks: raise ValueError('tasks must be a nonempty list')
    stock=Counter(initial)
    previous=-1
    ids=set()
    for task in tasks:
        if not isinstance(task,dict) or not {'id','release','kind','sku','source_dock'}<=task.keys():
            raise ValueError('each task needs id,release,kind,sku,source_dock')
        if type(task['id']) is not int or task['id'] in ids: raise ValueError('task IDs must be unique integers')
        ids.add(task['id'])
        release=task['release']
        if type(release) is not int or not 0<=release<close or release<previous: raise ValueError('release must be ordered integer seconds within [0,close_at)')
        previous=release
        if task['kind'] not in ('delivery','retrieval'): raise ValueError('kind must be delivery or retrieval')
        sku=task['sku']
        if type(sku) is not int or sku not in initial: raise ValueError('every integer SKU needs an initial stock entry')
        if type(task['source_dock']) is not int or task['source_dock']<1: raise ValueError('source_dock must be a positive integer')
        stock[sku]+=1 if task['kind']=='delivery' else -1
        if not 0<=stock[sku]<=initial[sku]+50: raise ValueError('stock prefix outside the fixed initial+50 allowance')
    return dict(orders=len(tasks),skus=len(initial),initial_stock=sum(initial.values()),seconds=close,
        outside_training_input_range=not(40<=len(tasks)<=240 and 1<=len(initial)<=5 and sum(initial.values())<=900 and close in (1800,3600)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-json',required=True,help='single case JSON: case,close_at,initial,tasks')
    parser.add_argument('--output',required=True,help='new JSON path; existing files are preserved')
    parser.add_argument('--seed',type=int,default=0,help='physical/GA seed, not exploration')
    args=parser.parse_args()
    case_path=Path(args.case_json).resolve()
    output=Path(args.output).resolve()
    if output.exists(): parser.error('output already exists; choose a new path')
    if output.suffix!='.json': parser.error('output must have a .json suffix')
    verify_baseline()
    manifest=read(FOLDER/'manifest.json')
    assert all(sha(ROOT/p)==digest for p,digest in manifest['hashes'].items()),'Model implementation source drift'
    selected=read(FOLDER/'selection.json')
    complete=read(FOLDER/'fit_complete.json')
    checkpoint=FOLDER/'best.npz'
    assert sha(checkpoint)==selected['checkpoint_sha256']==complete['best_sha256']
    protocol=read(ROOT/'data/adaptive_hungarian_learning_protocol.json')
    assert manifest['action_definition']==protocol['action_definition']==['hungarian_f_surrogate','joint_adaptive_ga']
    assert complete['epochs']==protocol['learning']['epochs']
    assert complete['selection_sha256']==sha(FOLDER/'selection.json')
    assert complete['latest_sha256']==sha(FOLDER/'latest.npz')
    curve=read(FOLDER/'learning_curve.json')
    assert [r['epoch'] for r in curve]==list(range(1,protocol['learning']['epochs']+1))
    case=read(case_path)
    inputs=validate_case(case)
    agent=MultiStepAgent.load(checkpoint)
    if agent.state_dim!=32: raise ValueError('checkpoint is not the new Hungarian/GA model')
    row=execute(case,protocol,agent,seed=args.seed)
    audit(row,case)
    row.update(phase='frozen_prediction',strategy='dqn',seed=args.seed,checkpoint_sha256=sha(checkpoint),
        case_sha256=sha(case_path),input_summary=inputs,
        action_definition=['hungarian_f_surrogate','joint_adaptive_ga'],
        warning='Input size or duration outside the training range; no performance guarantee.' if inputs['outside_training_input_range'] else None)
    output.parent.mkdir(parents=True,exist_ok=True)
    # 独占创建防止覆盖训练或测试记录；冻结检查在execute内部逐项执行。
    with output.open('x',encoding='utf-8') as stream: json.dump(row,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in row.items() if k not in ('transitions','losses','ga_searches')},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__': main()
