"""Compare online policies with the restricted exact oracle on tiny instances."""
import argparse
import json
import statistics
from baseline import run as baseline_run
from model import example
from optimized import run as optimized_run
from oracle import exact_static
from validation import validate

POLICIES = {
    'greedy': lambda s: baseline_run(s),
    'matching': lambda s: optimized_run(s, assignment='matching', joint=False),
    'joint': lambda s: optimized_run(s, assignment='greedy', joint=True),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=10)
    parser.add_argument('--tasks', type=int, default=4)
    parser.add_argument('--vehicles', type=int, default=2)
    parser.add_argument('--output', default='oracle_small_results.json')
    args = parser.parse_args()
    rows = []
    for seed in range(args.seeds):
        scenario = example(task_count=args.tasks, vehicles=args.vehicles, seed=seed)
        oracle = exact_static(scenario)
        validate(scenario, oracle)
        row = dict(seed=seed, oracle=oracle['mean_flow_time'],
                   oracle_makespan=oracle['makespan'],
                   oracle_evaluated=oracle['oracle']['evaluated_orders'])
        for name, policy in POLICIES.items():
            result = policy(scenario)
            validate(scenario, result)
            row[name] = result['mean_flow_time']
            row[name+'_gap_pct'] = 100*(result['mean_flow_time']-oracle['mean_flow_time'])/oracle['mean_flow_time']
        rows.append(row)
        print(seed, {k: round(row[k], 3) for k in ('oracle', 'greedy', 'matching', 'joint')})
    summary = {}
    for name in POLICIES:
        gaps = [r[name+'_gap_pct'] for r in rows]
        summary[name] = dict(mean_gap_pct=statistics.mean(gaps),
                             max_gap_pct=max(gaps),
                             wins=sum(g <= 1e-9 for g in gaps),
                             runs=len(gaps))
    output = dict(config=dict(seeds=args.seeds, tasks=args.tasks, vehicles=args.vehicles,
                              class_note='exact within no-deliberate-wait schedules; offline static'),
                  rows=rows, summary=summary)
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
