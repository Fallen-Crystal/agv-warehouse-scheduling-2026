"""动态订单验证场景；只展示模型可运行性，不评判算法优劣。"""
from pathlib import Path
import json
import csv
from model import example
from baseline import run
from validation import validate
from export_metrics import SUMMARY_FIELDS, export_details, audit_details


def main():
    output=Path(__file__).resolve().parent/'dynamic_examples'
    output.mkdir(exist_ok=True)
    rows=[]
    for arrival in ('batch','uniform','irregular','burst'):
        for demand in ('balanced','left_hotspot','right_hotspot','switching'):
            config=dict(mode='dynamic',arrival=arrival,demand=demand,seed=0)
            s=example(**config); result=run(s); validate(s,result)
            filename=arrival+'_'+demand+'.json'
            (output/filename).write_text(json.dumps(dict(config=config,scenario=s.to_dict(),result=result),ensure_ascii=False,indent=2),encoding='utf-8')
            export_details(result,output,arrival+'_'+demand)
            rows.append(dict(arrival=arrival,demand=demand,seed=0,last_release=max(j.release for j in s.tasks),
                **{k:result[k] for k in SUMMARY_FIELDS}))
    with (output/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # 保存后重新读取，用独立验证器检查而非只信任运行时结果。
    for p in output.glob('*.json'):
        from model import Scenario
        entry=json.loads(p.read_text(encoding='utf-8'))
        validate(Scenario.from_dict(entry['scenario']),entry['result'])
        audit_details(entry['result'],output,p.stem)
    print(f'PASS: {len(rows)} dynamic scenarios generated and independently reloaded; '+str(output))


if __name__=='__main__':
    main()
