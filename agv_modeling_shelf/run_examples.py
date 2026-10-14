"""导出固定样例和逐步轨迹；此为模型验证，不是算法优劣实验。"""
from pathlib import Path
import json
import csv
import hashlib
import platform
from model import example
from baseline import run
from validation import validate
from export_metrics import SUMMARY_FIELDS, export_details


def main():
    root = Path(__file__).resolve().parent
    output = root/'examples'
    output.mkdir(exist_ok=True)
    rows = []
    for mode in ('static', 'dynamic'):
        for layout in ('wide', 'bottleneck'):
            s = example(mode, layout, seed=0)
            result = run(s)
            validate(s, result)
            name = mode+'_'+layout
            (output/(name+'_input.json')).write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
            (output/(name+'_trace.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            export_details(result, output, name)
            rows.append(dict(mode=mode, layout=layout, **{k: result[k] for k in SUMMARY_FIELDS}))
    with (output/'summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    manifest = dict(python=platform.python_version(), policy='static_distance_greedy', seed=0,
        unit='discrete_step', task_count=12, vehicles=4,
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))})
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
