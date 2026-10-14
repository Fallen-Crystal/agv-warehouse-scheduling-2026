"""Paired experiments and ablations, identical serialized input for all solvers."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time
from baseline import run as baseline_run
from optimized import run as optimized_run
from model import example
from scenario_io import scenario_id
from validation import validate

CONFIGS = {
 'static_small_wide': dict(mode='static',size='small',vehicles=4,layout='wide',task_count=12),
 'static_small_bottleneck': dict(mode='static',size='small',vehicles=4,layout='bottleneck',task_count=12),
 'dynamic_medium_burst': dict(mode='dynamic',size='medium',vehicles=6,layout='bottleneck',task_count=30,arrival='burst'),
 'dynamic_large_shared': dict(mode='dynamic',size='large',vehicles=8,layout='bottleneck',task_count=40,arrival='irregular',delivery_pattern='shared'),
 'dynamic_small_switching': dict(mode='dynamic',size='small',vehicles=4,layout='bottleneck',task_count=30,arrival='irregular',demand='switching'),
 'short_horizon_stress': dict(mode='static',size='medium',vehicles=6,layout='bottleneck',task_count=30,horizon=100),
}
SOLVERS = {
 'baseline': baseline_run,
 'matching_only': lambda s: optimized_run(s,joint=False),
 'joint_only': lambda s: optimized_run(s,assignment='greedy'),
 'matching_joint': optimized_run,
}
FIELDS=('makespan','mean_flow_time','p90_flow_time','moves','empty_moves','loaded_moves','traffic_wait_steps','mean_dispatch_wait','mean_pickup_duration','mean_loaded_duration')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seeds',type=int,default=10)
    parser.add_argument('--output',default='algorithm_results');args=parser.parse_args()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    rows=[]; comparisons=[]
    for name,config in CONFIGS.items():
        for seed in range(args.seeds):
            s=example(**config,seed=seed); digest=scenario_id(s)
            (root/f'{name}_{seed}_input.json').write_text(json.dumps(s.to_dict(),ensure_ascii=False))
            for solver,fn in SOLVERS.items():
                start=time.perf_counter();r=fn(s);elapsed=time.perf_counter()-start
                validate(s,r)
                row=dict(scenario=name,seed=seed,solver=solver,sha256=digest,feasible=r['feasible'],
                         completed=r['completed'],total_tasks=r['total_tasks'],runtime_seconds=elapsed,
                         accepted_replans=len(r['replanning_events']),
                         **{f:r[f] for f in FIELDS})
                rows.append(row)
                (root/f'{name}_{seed}_{solver}.json').write_text(json.dumps(r,ensure_ascii=False))
            print(name,seed,'validated',flush=True)
    with (root/'runs.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    for name in CONFIGS:
        for solver in SOLVERS:
            own=[r for r in rows if r['scenario']==name and r['solver']==solver]
            baseline={r['seed']:r for r in rows if r['scenario']==name and r['solver']=='baseline'}
            paired=[(baseline[r['seed']],r) for r in own if r['feasible'] and baseline[r['seed']]['feasible']]
            summary=dict(scenario=name,solver=solver,successes=sum(r['feasible'] for r in own),runs=len(own),
                         completed_mean=statistics.mean(r['completed'] for r in own),paired_successes=len(paired),
                         runtime_mean=statistics.mean(r['runtime_seconds'] for r in own),
                         replans_mean=statistics.mean(r['accepted_replans'] for r in own))
            for field in FIELDS:
                a=[b[field] for b,r in paired];b=[r[field] for base,r in paired]
                summary[field+'_baseline']=statistics.mean(a) if a else None
                summary[field+'_mean']=statistics.mean(b) if b else None
                summary[field+'_improvement_pct']=100*(sum(a)-sum(b))/sum(a) if a and sum(a) else None
            summary['flow_wins']=sum(r['mean_flow_time']<b['mean_flow_time'] for b,r in paired)
            summary['flow_ties']=sum(r['mean_flow_time']==b['mean_flow_time'] for b,r in paired)
            summary['flow_losses']=sum(r['mean_flow_time']>b['mean_flow_time'] for b,r in paired)
            comparisons.append(summary)
    (root/'summary.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2))
    with (root/'summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(comparisons[0]));w.writeheader();w.writerows(comparisons)
    (root/'manifest.json').write_text(json.dumps(dict(configs=CONFIGS,seeds=list(range(args.seeds)),
        python=platform.python_version(),platform=platform.platform(),solver_options=dict(interval=5,attempts=8,age_weight=.25),
        validation='every trace checked by independent validation.py',
        note='Costs paired only when both runs finish all tasks AND return home; failures are retained.',
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('.').glob('*.py')}),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
