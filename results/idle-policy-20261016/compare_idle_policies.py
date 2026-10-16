"""Frozen paired experiment, separate from production profiles and algorithms."""
from pathlib import Path
import csv,hashlib,json,os,random,sys,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT/'work/agv-repository-source/Fallen-Crystal-agv-warehouse-scheduling-2026-dee48a4'
OUT=ROOT/'outputs/agv_idle_policy_comparison_20261016'
sys.path.insert(0,str(REPO/'src'))
from agv.domain import Scenario
from agv.warehouse.mixed import generate
from agv.simulation import Environment
from agv.dispatch.bcrd import fallback
from agv.dispatch.idle import hold_return
from agv.evaluation.validation import validate
from agv.io.scenes import scenario_id

SIZES=('medium','large','xlarge','xxlarge')
SEEDS=(101,102,103)
TEMPLATES={
 'dense_static':dict(vehicles=6,task_count=12,delivery_pattern='distributed',demand='balanced'),
 'sparse_uniform':dict(vehicles=4,task_count=12,delivery_pattern='distributed',demand='balanced'),
 'shared_bursts':dict(vehicles=8,task_count=12,delivery_pattern='shared',demand='switching'),
}

def allowed_near_delivery(s,point,destination):
    distance=abs(point[0]-destination[0])+abs(point[1]-destination[1])
    # No service/parking cells and no immediate egress of any delivery station.
    return (point in s.transit_only and 2<=distance<=3
            and all(abs(point[0]-d[0])+abs(point[1]-d[1])>1 for d in s.stations))

def execute(s,policy,cap):
    env=Environment(s,router_kind='sipp',idle_hold_steps=0)
    checks=rejects=0
    while not env.done and env.time<cap:
        # Equivalent to empty fallback calls when no visible pending/available pair.
        pending=any(j not in env._assigned for j in env._released_jobs)
        feedback=env.assign(fallback(env.observe())) if pending and any(a is None for a in env._active) else []
        if env.stop_if_stalled(feedback):break
        ready=env._stream_closed and not pending and all(a is None for a in env._active)
        if policy=='near_delivery' and not ready:
            for k,path in enumerate(env._plans):
                if env._active[k] is not None or len(path)<=1:continue
                last=next((r for r in reversed(env._records) if r['vehicle']==k),None)
                if last is None:continue
                job=env._released_jobs[last['task_id']]
                if not allowed_near_delivery(s,path[0],job.delivery):continue
                checks+=1
                try:hold_return(env,k)
                except ValueError:rejects+=1
        env.advance(observe=False)
    r=env.result()
    validate(s,r)
    assert r['order_stream_closed'] if 'order_stream_closed' in r else env._stream_closed
    for w in r['idle_waits']:
        for t in range(w['start'],min(w['end'],r['time'])):
            last=next(x for x in reversed(r['assignments']) if x['vehicle']==w['vehicle'] and x['assigned_at']<=t)
            assert allowed_near_delivery(s,r['paths'][w['vehicle']][t],env._released_jobs[last['task_id']].delivery)
    r['research']=dict(policy=policy,computational_cutoff=not env.done and env.time>=cap,
                       hold_attempts=checks,hold_rejections=rejects,independent_audit=True)
    return r

def make_scene(size,template,seed):
    opts=TEMPLATES[template]
    s=generate(mode='static',size=size,seed=seed,shelf_layers=3,horizon=None,**opts)
    releases=[0 if template=='dense_static' else i*100 if template=='sparse_uniform' else i//4*250 for i in range(len(s.tasks))]
    s.tasks=[replace(j,release=t) for j,t in zip(s.tasks,releases)]
    s.order_stream_end=max(releases,default=0)
    return s.check()

def pair(case):
    size,template,seed=case;s=make_scene(*case)
    name=f'{size}_{template}_{seed}';(OUT/'inputs'/f'{name}.json').write_text(json.dumps(s.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    cap=s.order_stream_end+2000
    order=['near_delivery','return_interruptible']
    random.Random(seed+100*SIZES.index(size)+TEMPLATES[template]['vehicles']).shuffle(order)
    rows=[]
    for policy in order:
        start=time.perf_counter();r=execute(s,policy,cap)
        (OUT/'traces'/f'{name}_{policy}.json').write_text(json.dumps(r,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        fields=('feasible','completed','total_tasks','makespan','mean_flow_time','p90_flow_time','moves','empty_moves','loaded_moves','time','traffic_wait_steps','standby_steps','workload_cv')
        rows.append(dict(case=name,size=size,template=template,seed=seed,policy=policy,scenario_sha256=scenario_id(s),energy=.05*r['moves'],wall_seconds=time.perf_counter()-start,hold_rejections=r['research']['hold_rejections'],cutoff=r['research']['computational_cutoff'],**{k:r[k] for k in fields}))
    return rows

def manifest_sources():
    return {p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (REPO/'src/agv').rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def main():
    OUT.mkdir(exist_ok=True)
    for folder in ('inputs','traces'):(OUT/folder).mkdir(exist_ok=True)
    cases=[(size,t,seed) for size in SIZES for t in TEMPLATES for seed in SEEDS]
    plan=dict(question='near-delivery standby until explicit stream end vs interruptible home return',cases=len(cases),runs=2*len(cases),sizes=SIZES,seeds=SEEDS,templates=TEMPLATES,
        policies=['near_delivery','return_interruptible'],same_scene_per_pair=True,same_greedy_dispatch=True,same_sipp=True,
        standby_zone='ordinary transit L1 distance 2..3 from last D; excludes immediate egress of every D',
        final_return_in_both=True,energy_proxy='.05 * all moves including final return',
        main_score='0.5*T/T_return +0.3*R/R_return +0.2*D/D_return; fixed scheme-2 reference per scene, not production A* denominators',
        computational_cap='last_release+2000, report cutoff separately, not a physical deadline',
        uncertainty='3 independent seeds per size/template; exploratory, no population-wide optimality claim',
        frozen_source_sha256=manifest_sources(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'protocol.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(pair,c):c for c in cases}
        for future in as_completed(futures):
            group=future.result();rows.extend(group)
            with (OUT/'runs.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            print(f'Completed {len(rows)//2}/{len(cases)}: {group[0]["case"]}; success {[x["feasible"] for x in group]}',flush=True)
    assert plan['frozen_source_sha256']==manifest_sources(),'Production source changed during research'
    print('ALL_DONE: paired traces independently validated; production source unchanged',flush=True)

if __name__=='__main__':main()
