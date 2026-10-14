"""Optional figure generation: uv run --with matplotlib python plot_results.py."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path('algorithm_results');rows=json.loads((root/'summary.json').read_text())
    names=[r['scenario'] for r in rows if r['solver']=='baseline' and r['successes']==r['runs']]
    labels=['Small / wide','Small / bottleneck','Medium / burst','Large / shared','Small / switching']
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    colors=['#767E8B','#DC9760','#278477','#4366AE']
    for n,solver in enumerate(['baseline','matching_only','joint_only','matching_joint']):
        own=[next(r for r in rows if r['scenario']==name and r['solver']==solver) for name in names]
        x=[i+(n-1.5)*.2 for i in range(len(names))]
        axes[0].bar(x,[r['mean_flow_time_mean'] for r in own],.19,label=solver,color=colors[n])
        if n:axes[1].plot(range(len(names)),[r['mean_flow_time_improvement_pct'] for r in own],marker='o',label=solver,color=colors[n])
    axes[0].set_ylabel('Mean order flow time (steps)');axes[0].set_title('Paired 10-seed averages')
    axes[1].set_ylabel('Reduction vs baseline (%)');axes[1].set_title('Improvement can depend on the scenario')
    axes[1].axhline(0,color='#888888',linewidth=.8)
    for ax in axes:
        ax.set_xticks(range(len(names)),labels,rotation=20,ha='right');ax.legend(fontsize=8);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.savefig(root/'comparison.png',dpi=180);fig.savefig(root/'comparison.pdf')


if __name__=='__main__':main()
