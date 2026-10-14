"""Independently audit all saved formal results without rerunning planners."""
import json
import hashlib
from pathlib import Path
from model import Scenario
from validation import validate


def main():
    root=Path('algorithm_results');count=0
    manifest=json.loads((root/'manifest.json').read_text())
    for name in manifest['configs']:
        for seed in manifest['seeds']:
            s=Scenario.from_dict(json.loads((root/f'{name}_{seed}_input.json').read_text()))
            for solver in ('baseline','matching_only','joint_only','matching_joint'):
                r=json.loads((root/f'{name}_{seed}_{solver}.json').read_text())
                validate(s,r);count+=1
    core=('model.py','routing.py','pickup_planning.py','baseline.py','optimized.py','joint_planning.py','environment.py','metrics.py','validation.py','benchmark_algorithms.py')
    require_match={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==manifest['sources'][p] for p in core}
    if not all(require_match.values()):raise ValueError('Core benchmark source differs: '+str(require_match))
    print(json.dumps(dict(saved_traces_validated=count,core_sources_match=True),indent=2))


if __name__=='__main__':main()
