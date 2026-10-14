"""从保存文件独立复核，防止输出与说明或源代码不一致。"""
from pathlib import Path
import json
import csv
import hashlib
from math import isclose
from model import Scenario
from validation import validate
from export_metrics import SUMMARY_FIELDS, audit_details


def main():
    root = Path(__file__).resolve().parent
    output = root/'examples'
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Source changed: '+name)
    with (output/'summary.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    expected = {(m, l) for m in ('static', 'dynamic') for l in ('wide', 'bottleneck')}
    if len(rows) != 4 or {(r['mode'], r['layout']) for r in rows} != expected:
        raise ValueError('Missing or duplicate scenario')
    scenarios = {}
    for row in rows:
        name = row['mode']+'_'+row['layout']
        s = Scenario.from_dict(json.loads((output/(name+'_input.json')).read_text(encoding='utf-8')))
        r = json.loads((output/(name+'_trace.json')).read_text(encoding='utf-8'))
        validate(s, r)
        audit_details(r,output,name)
        if not r['feasible'] or row['feasible'] != 'True':
            raise ValueError('Example incomplete')
        for key in (k for k in SUMMARY_FIELDS if k not in ('feasible','comparison_valid','metrics_scope')):
            if not isclose(float(row[key]), r[key]):
                raise ValueError('Summary mismatch: '+key)
        if row['comparison_valid'] != str(r['comparison_valid']) or row['metrics_scope'] != r['metrics_scope']:
            raise ValueError('Comparison validity mismatch')
        scenarios[row['mode'], row['layout']] = s
    for layout in ('wide', 'bottleneck'):
        a, b = scenarios['static', layout], scenarios['dynamic', layout]
        if [(j.pickup,j.shelf,j.delivery) for j in a.tasks] != [(j.pickup,j.shelf,j.delivery) for j in b.tasks]:
            raise ValueError('Task pairing mismatch')
    print('PASS: 4 saved scenarios; input, trajectory, summary, paired tasks and source hashes verified')


if __name__ == '__main__':
    main()
