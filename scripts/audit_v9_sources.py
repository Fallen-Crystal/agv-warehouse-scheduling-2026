#!/usr/bin/env python3
"""Reproduce upstream V9 counterexamples in a disposable copy, never the source.

The supplied directory is reviewed Python source, explicitly selected by the
caller. This tool runs its original model/executor/validator with fixed public
fixtures and records source hashes. It does not launch its server or overwrite
its examples. Use after timed policy experiments, not concurrently with them.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = r"""
import copy,json
from model import Task,example
from environment import Environment
from validation import validate
s=example(task_count=0,vehicles=1,size='medium',obstacle_layout='columns_equipment')
row=max((r for r in s.map_info['rack_catalog'] if r['face']=='R'),key=lambda r:r['position'][1])
s.tasks=[Task(0,None,s.stations[-1],pickup_service=2,shelf=tuple(row['position']))]
s.check()
future=copy.deepcopy(s)
future.tasks.append(Task(1,None,s.stations[-1],release=500,pickup_service=2,shelf=tuple(row['position'])))
future.check()
left,right=Environment(s),Environment(future)
assert left.assign([(0,0)])[0]['accepted'] and right.assign([(0,0)])[0]['accepted']
when=left._records[0]['delivery_end']+1
left.advance(when);right.advance(when)
same=left.observe()==right.observe()
before=list(left._plans[0][0])
left.advance();right.advance()
causal=dict(equal_observations_before=same,time_before=when,position_before=before,
           without_hidden_order=list(left._plans[0][0]),with_hidden_order=list(right._plans[0][0]),
           next_positions_differ=left._plans[0][0]!=right._plans[0][0])
while not left.done:left.advance()
original=left.result();validate(s,original)
forged=copy.deepcopy(original)
for collection in ('events','assignments'):
    forged[collection][-1]['return_end']=forged['time']+1
    forged[collection][-1]['return_arrival']=forged['time']+1
try:validate(s,forged);accepted=True
except ValueError:accepted=False
print(json.dumps(dict(causality=causal,original_complete=original['feasible'],
                      forged_final_return_after_execution_accepted=accepted),sort_keys=True))
"""


def audit(source, output):
    source = Path(source).resolve()
    if not (source / "idle_control.py").is_file():
        raise ValueError("Expected the upstream V9 source directory")
    hashes = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(source.glob("*.py"))
    }
    with tempfile.TemporaryDirectory(prefix="agv-v9-source-audit-") as temporary:
        copied = Path(temporary) / "source"
        shutil.copytree(source, copied, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        run = subprocess.run(
            [sys.executable, "-c", PROBE], cwd=copied, check=True, capture_output=True, text=True
        )
    findings = json.loads(run.stdout)
    if not findings["causality"]["equal_observations_before"]:
        raise ValueError("The causality fixture did not establish equal observations")
    report = dict(
        schema="agv-v9-upstream-audit-v1",
        source_name=source.name,
        source_python_sha256=hashes,
        findings=findings,
        scope="Counterexamples to the original V9 package, not the reviewed bounded controller",
    )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.source, args.output), ensure_ascii=False, indent=2))
