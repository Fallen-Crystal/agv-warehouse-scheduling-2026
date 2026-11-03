"""Independently audit all saved formal results without rerunning planners."""
import argparse
import json
import hashlib
from pathlib import Path
from model import Scenario
from validation import validate

CORE=('model.py','routing.py','pickup_planning.py','baseline.py','optimized.py','joint_planning.py','environment.py','metrics.py','validation.py','benchmark_algorithms.py')
COMPARE=('feasible','completed','makespan','mean_flow_time','moves','empty_moves','loaded_moves')


def solvers():
    from baseline import run as baseline_run
    from optimized import run as optimized_run
    return {
        'baseline': baseline_run,
        'matching_only': lambda s: optimized_run(s, joint=False),
        'joint_only': lambda s: optimized_run(s, assignment='greedy'),
        'matching_joint': optimized_run,
    }


def rerun_all(root, manifest):
    functions = solvers()
    checked = mismatches = 0
    for name in manifest['configs']:
        for seed in manifest['seeds']:
            scenario = Scenario.from_dict(json.loads((root/f'{name}_{seed}_input.json').read_text()))
            for solver, function in functions.items():
                expected = json.loads((root/f'{name}_{seed}_{solver}.json').read_text())
                actual = function(scenario)
                validate(scenario, actual)
                for field in COMPARE:
                    checked += 1
                    if actual[field] != expected[field]:
                        mismatches += 1
                        if mismatches <= 10:
                            print(f'{name} seed={seed} {solver} {field}: '
                                  f'{actual[field]} != {expected[field]}')
    if mismatches:
        raise ValueError(f'Rerun metrics differ in {mismatches}/{checked} fields')
    return dict(runs=len(manifest['configs'])*len(manifest['seeds'])*len(functions),
                fields_checked=checked, mismatches=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rerun', action='store_true',
                        help='re-run all 240 saves with current code and compare metrics')
    args = parser.parse_args()
    root = Path('algorithm_results'); count = 0
    manifest = json.loads((root/'manifest.json').read_text())
    for name in manifest['configs']:
        for seed in manifest['seeds']:
            s = Scenario.from_dict(json.loads((root/f'{name}_{seed}_input.json').read_text()))
            for solver in ('baseline','matching_only','joint_only','matching_joint'):
                r = json.loads((root/f'{name}_{seed}_{solver}.json').read_text())
                validate(s, r); count += 1
    current = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in CORE}
    original = all(current[p] == manifest['sources'][p] for p in CORE)
    revision = None
    perf_path = Path('../artifacts/perf_refactor_2026-11-03.json')
    if not original and perf_path.exists():
        perf = json.loads(perf_path.read_text())
        if perf.get('metric_mismatches') == [] and all(
                current[p] == perf.get('source_hashes', {}).get(p) for p in CORE):
            revision = 'perf_refactor_2026-11-03'
    if not original and revision is None:
        raise ValueError('Core benchmark source differs from both the formal manifest and the documented refactor')
    report = dict(saved_traces_validated=count, core_sources_match=True,
                  source_revision=revision or 'formal_manifest')
    if args.rerun:
        report['rerun'] = rerun_all(root, manifest)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
