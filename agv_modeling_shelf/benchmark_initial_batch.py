"""Compare the default joint policy with the optional static batch planner."""
import argparse
import json
import statistics
import time
from model import example
from optimized import run
from validation import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=10)
    parser.add_argument('--output', default='initial_batch_results.json')
    args = parser.parse_args()
    rows = []
    for layout in ('wide', 'bottleneck'):
        for seed in range(args.seeds):
            scenario = example(seed=seed, layout=layout)
            normal = run(scenario, assignment='greedy', joint=True)
            validate(scenario, normal)
            start = time.perf_counter()
            batch = run(scenario, assignment='greedy', joint=True, initial_rollout=True)
            elapsed = time.perf_counter() - start
            validate(scenario, batch)
            rows.append(dict(layout=layout, seed=seed,
                             joint=normal['mean_flow_time'],
                             batch=batch['mean_flow_time'],
                             improvement_pct=100*(normal['mean_flow_time']-batch['mean_flow_time'])/normal['mean_flow_time'],
                             batch_seconds=elapsed))
            print(layout, seed, round(normal['mean_flow_time'], 3),
                  round(batch['mean_flow_time'], 3), round(elapsed, 2))
    summary = {}
    for layout in ('wide', 'bottleneck'):
        own = [r for r in rows if r['layout'] == layout]
        summary[layout] = dict(
            joint=statistics.mean(r['joint'] for r in own),
            batch=statistics.mean(r['batch'] for r in own),
            improvement_pct=statistics.mean(r['improvement_pct'] for r in own),
            batch_seconds=statistics.mean(r['batch_seconds'] for r in own))
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump(dict(config=dict(seeds=args.seeds, class_note='static only; optional batch mode'),
                       rows=rows, summary=summary), handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
