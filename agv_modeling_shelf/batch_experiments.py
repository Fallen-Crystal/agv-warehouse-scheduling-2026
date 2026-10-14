"""同场景多种子批量运行；失败率与成功成绩分别统计。"""
from pathlib import Path
from datetime import datetime
import csv
import json
import statistics
import time
import hashlib
from model import example
from baseline import run, greedy_action
from validation import validate
from scenario_io import scenario_id, save_scene
from export_metrics import SUMMARY_FIELDS, export_details

COMPARE_FIELDS=('makespan','mean_flow_time','max_flow_time','p90_flow_time','moves','empty_moves','loaded_moves')


def aggregate(rows):
    summaries=[]
    for policy in sorted({r['policy'] for r in rows}):
        own=[r for r in rows if r['policy']==policy]
        good=[r for r in own if r['feasible']]
        summary=dict(policy=policy,runs=len(own),successes=len(good),failures=len(own)-len(good),
            success_rate=len(good)/len(own),mean_completion_rate=statistics.mean(r['completion_rate'] for r in own))
        for field in COMPARE_FIELDS:
            values=[r[field] for r in good]
            summary[field+'_mean']=statistics.mean(values) if values else None
            summary[field+'_std']=statistics.stdev(values) if len(values)>1 else None
        summaries.append(summary)
    return summaries


def run_batch(config,seeds,policies=None,output_dir=None):
    seeds=list(seeds)
    if not seeds or len(seeds)>20 or len(set(seeds))!=len(seeds) or any(type(s) is not int or not 0<=s<=999999 for s in seeds):
        raise ValueError('任务种子需为1到20个不重复的非负整数，最大999999')
    policies={'distance':greedy_action} if policies is None else policies
    if not policies or any(not isinstance(name,str) or not callable(fn) for name,fn in policies.items()):
        raise ValueError('策略需为名称到可调用函数的映射')
    rows=[];entries=[]
    if output_dir is not None:Path(output_dir).mkdir(parents=True,exist_ok=False)
    for seed in seeds:
        options={**config,'seed':seed};scenario=example(**options)
        digest=scenario_id(scenario)
        for name,policy in policies.items():
            start=time.perf_counter();result=run(scenario,policy);elapsed=time.perf_counter()-start
            validate(scenario,result)
            row=dict(policy=name,seed=seed,scenario_sha256=digest,runtime_seconds=elapsed,
                reason=result['reason'],planning_failure_count=result['diagnostics']['planning_failure_count'],
                **{k:result[k] for k in SUMMARY_FIELDS})
            rows.append(row)
            entry=dict(config=options,scenario=scenario.to_dict(),result=result,policy=name,runtime_seconds=elapsed,scenario_sha256=digest)
            entries.append(entry)
            if output_dir is not None:
                stem='run_'+str(len(rows))+'_seed_'+str(seed)
                save_scene(Path(output_dir)/(stem+'.json'),scenario,options,result)
                (Path(output_dir)/(stem+'_diagnostics.json')).write_text(json.dumps(result['diagnostics'],ensure_ascii=False,indent=2),encoding='utf-8')
                export_details(result,output_dir,stem)
    summaries=aggregate(rows)
    for summary in summaries:
        summary.update(scenario_config=json.dumps({k:v for k,v in config.items() if k!='seed'},ensure_ascii=False,sort_keys=True),task_seeds=';'.join(map(str,seeds)))
    if output_dir is not None:
        root=Path(output_dir)
        for filename,data in [('runs.csv',rows),('summary.csv',summaries)]:
            with (root/filename).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
        manifest=dict(config=config,seeds=seeds,policies=list(policies),
            note='均值及样本标准差仅统计成功运行；成功率和完成率包含失败运行。环境执行耗时包含调度和路径规划，不是纯算法耗时。',
            sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parent.glob('*.py')})
        (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(config={k:v for k,v in config.items() if k!='seed'},seeds=seeds,rows=rows,summaries=summaries,entries=entries)


def main():
    config=dict(mode='dynamic',arrival='irregular',size='small',vehicles=4,layout='bottleneck',task_count=12)
    destination=Path(__file__).resolve().parent/'batch_results'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    report=run_batch(config,range(5),output_dir=destination)
    print('批量实验已保存：'+str(destination))
    print(json.dumps(report['summaries'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
