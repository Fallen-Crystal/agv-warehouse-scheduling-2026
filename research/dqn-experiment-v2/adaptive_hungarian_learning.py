"""在历史训练适配器之外替换GA算子，DQN与纯GA严格共用双概率自适应实现。"""
from unittest.mock import patch
import adaptive_genetic
from hungarian_learning import MultiStepAgent,LearningPolicy,learning_observation
from hungarian_learning import execute as previous_execute

ADAPTATION=dict(version='joint-adaptive-rates-v2',initial_mutation_rate=.7,initial_crossover_rate=.9,
    mutation_bounds=[.05,.95],crossover_bounds=[.55,.95],population=12,elites=2,
    mutation_formula='clip(.7*(1+.20*stagnant+.60*(1-diversity)),.05,.95)',
    owner_mutation_formula='min(.95,mutation_rate+.1)',
    crossover_formula='clip(.9-.04*stagnant-.20*(1-diversity),.55,.95)',
    diversity='unique(order, owner-vector) / population',proxy_budget=192,generations=16,previews=6)


def audit_adaptation(row):
    """检查实际逐代记录；没有GA搜索时允许空列表，保留原计划缓存语义。"""
    assert row['ga_adaptation']==ADAPTATION
    if row.get('observation_schema')=='published-hour-v3-32':
        assert row['action_definition']==['hungarian_f_surrogate','joint_adaptive_ga']
    for search in row['ga_searches']:
        assert search['adaptive_mutation'] and search['adaptive_crossover']
        assert 0<=search['proxy_evaluations']<=192 and 0<=search['candidates']<=192
        history=search['mutation_history']
        assert 0<len(history)<=16
        assert [h['generation'] for h in history]==list(range(len(history)))
        for h in history:
            mutation=max(.05,min(.95,.7*(1+.20*h['stagnant']+.60*(1-h['diversity']))))
            crossover=max(.55,min(.95,.9-.04*h['stagnant']-.20*(1-h['diversity'])))
            assert abs(h['mutation_rate']-mutation)<1e-12 and abs(h['crossover_rate']-crossover)<1e-12
            assert h['owner_mutation_rate']==min(.95,mutation+.1)
            assert h['crossover_attempts']==10 and 0<=h['crossovers']<=10
            assert 0<=h['order_mutations']<=10 and 0<=h['owner_mutations']<=10
            assert 0<=h['diversity']<=1 and h['stagnant']>=0


def execute(case,protocol,agent=None,*,training=False,strategy='dqn',seed=0):
    """替换候选生成器，不修改匹配、奖励、物理执行、GA预览预算或缓存。"""
    searches=[]
    def candidates(*args,**kwargs):
        kwargs.update(adaptive_mutation=True,adaptive_crossover=True,mutation_rate=.7,crossover_rate=.9)
        plans,meta=adaptive_genetic.candidates(*args,**kwargs)
        searches.append(dict(time=args[0].world.time,**{key:meta[key] for key in
            ('proxy_evaluations','candidates','mutation_history','adaptive_mutation','adaptive_crossover')}))
        return plans,meta
    with patch('improved.policy.candidates',candidates):
        row=previous_execute(case,protocol,agent,training=training,strategy=strategy,seed=seed)
    row['ga_adaptation']=ADAPTATION.copy()
    row['ga_searches']=searches
    if strategy=='dqn': row['action_definition']=['hungarian_f_surrogate','joint_adaptive_ga']
    return row
