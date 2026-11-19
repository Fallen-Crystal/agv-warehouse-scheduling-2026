"""仅在训练、验证及五日期四策略测试全部审计通过后发布中文结果。"""
import csv
import io
import json
from paths import ROOT,sha
from run_adaptive_hungarian_learning import FOLDER,read,write
from audit_adaptive_hungarian_learning import analyze

LABELS={'ga':'纯自适应GA','exact':'原精准匹配','hungarian':'纯匈牙利'}

def summarize_adaptation(rows):
    """汇总真实搜索日志；没有调用GA时明确给出空范围，不能伪造默认概率。"""
    searches=[search for row in rows for search in row['ga_searches']]
    history=[h for search in searches for h in search['mutation_history']]
    def limits(key):
        values=[h[key] for h in history]
        return [min(values),max(values)] if values else None
    attempts=sum(h['crossover_attempts'] for h in history)
    crosses=sum(h['crossovers'] for h in history)
    return dict(searches=len(searches),generations=len(history),
        mutation_range=limits('mutation_rate'),owner_mutation_range=limits('owner_mutation_rate'),
        crossover_range=limits('crossover_rate'),
        crossover_attempts=attempts,crossovers=crosses,
        crossover_trigger_fraction=crosses/attempts if attempts else None,
        order_mutations=sum(h['order_mutations'] for h in history),owner_mutations=sum(h['owner_mutations'] for h in history),
        total_proxy_evaluations=sum(s['proxy_evaluations'] for s in searches),
        max_proxy_evaluations_per_search=max((s['proxy_evaluations'] for s in searches),default=0))


def publish(report):
    if not report['complete']:
        return False
    selected=report['selection']
    # 防止调用者传入过期审计，却在报告中记录另一个当前模型的身份。
    model_digest=sha(FOLDER/'best.npz')
    if model_digest!=selected['checkpoint_sha256']:
        raise ValueError('Model identity differs from audited selection; publication refused')
    protocol=read(ROOT/'data/adaptive_hungarian_learning_protocol.json')
    means=report['mean_paired_improvement_percent']
    success=all(v>1e-8 for v in means.values())
    every_pair=all(v>1e-8 for t in report['test'] for v in t['improvement_percent'].values())
    wins={key:dict(better=sum(t['improvement_percent'][key]>1e-8 for t in report['test']),
        equal=sum(abs(t['improvement_percent'][key])<=1e-8 for t in report['test']),
        worse=sum(t['improvement_percent'][key]<-1e-8 for t in report['test'])) for key in LABELS}
    result=dict(**report,average_goal_achieved=success,all_date_pairs_improved=every_pair,paired_counts=wins,
        model_sha256=model_digest,auditor_sha256=sha(ROOT/'audit_adaptive_hungarian_learning.py'))
    result['ga_adaptation']=protocol['ga_adaptation']
    result['test_ga_adaptation']={strategy:summarize_adaptation([
        read(FOLDER/f'test_{index:02d}_{strategy}.json') for index in range(len(report['test']))]) for strategy in ('ga','dqn')}
    stream=io.StringIO(newline='')
    fields=['day','case','minutes','orders','dqn_F','ga_F','exact_F','hungarian_F',
        'improvement_vs_ga_percent','improvement_vs_exact_percent','improvement_vs_hungarian_percent','dqn_hungarian_actions','dqn_ga_actions']
    writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
    for t in report['test']:
        writer.writerow(dict(day=t['day'],case=t['case'],minutes=t['minutes'],orders=t['orders'],
            **{f'{key}_F':t['F'][key] for key in ('dqn','ga','exact','hungarian')},
            **{f'improvement_vs_{key}_percent':t['improvement_percent'][key] for key in LABELS},
            dqn_hungarian_actions=t['actions'].get('hungarian',0),dqn_ga_actions=t['actions'].get('ga',0)))
    lines=['# 匈牙利与GA双动作DQN重训练结果','',
        ('五个未使用日期上的平均配对F同时低于三个固定基线，达到本轮平均改善目标。' if success else
         '五个未使用日期上的平均配对F未同时低于三个固定基线，本轮尚未达到平均改善目标。'),'',
        '这与每个日期都更好是不同的要求：'+('本次全部15个日期/基线配对均改善。' if every_pair else '本次仍有部分日期/基线配对持平或退化。'),'',
        '正改善率表示DQN的正式F更低。每个配对使用同一完整订单、同一物理seed=0和同一GA预算。', '',
        '| 基线 | 平均配对改善率 | 更好/持平/更差日期数 |','|---|---:|---:|']
    for key,label in LABELS.items():
        count=wins[key]
        lines.append(f"| {label} | {means[key]:+.6f}% | {count['better']}/{count['equal']}/{count['worse']} |")
    lines+=['','## 未见日期逐项比较','','| 源日期编号 | 分钟 | 订单 | DQN F | 纯GA F | 精准匹配 F | 匈牙利 F |',
        '|---:|---:|---:|---:|---:|---:|---:|']
    for t in report['test']:
        f=t['F']
        lines.append(f"| {t['day']} | {t['minutes']} | {t['orders']} | {f['dqn']:.9f} | {f['ga']:.9f} | {f['exact']:.9f} | {f['hungarian']:.9f} |")
    lines+=['','## 训练与验证选模','',
        f"从零训练{protocol['learning']['epochs']}轮，共{report['training_windows']}个训练窗口、{report['training_decisions']}个决策转移、{report['train_steps']}次梯度更新。唯一训练订单1327条；重复训练不会增加不同订单数。",'',
        '网络为32-64-2 ReLU Double DQN，gamma=1，5步回报，每次新决策做4次回放更新。新动作0为F局部代理匈牙利，动作1为双概率自适应joint GA；经验池不含旧精准匹配动作语义。', '',
        f"按照验证集相对三基线平均F比值中最差者最小的规则，选择第{selected['epoch']}轮。最终测试不参与检查点选择。",'',
        '| 轮次 | 对GA改善 | 对精准改善 | 对匈牙利改善 |','|---:|---:|---:|---:|']
    for v in report['validation_epochs']:
        ratios=v['mean_ratios']
        lines.append(f"| {v['epoch']} | {100*(1-ratios['ga']):+.6f}% | {100*(1-ratios['exact']):+.6f}% | {100*(1-ratios['hungarian']):+.6f}% |")
    actions={key:sum(t['actions'].get(key,0) for t in report['test']) for key in ('hungarian','ga')}
    lines+=['','## 自主动作与固定条件','',
        f"最终测试中，DQN选择匈牙利{actions['hungarian']}次、GA {actions['ga']}次。推断使用网络Q值贪心选择，不使用固定负荷阈值或测试日期编号。",'',
        '正式F始终为0.5T/900+0.3R/900+0.2D/5400。62×47、6台AGV、5层、1格/秒、SIPP和GA预算proxy192/previews6/generations16/gate=False保持一致；DQN与纯GA共用同一双概率自适应算子及相同计划缓存。原精准匹配是精确DP，匈牙利局部成本代理不能宣称全时域最优。', '',
        '每条轨迹先通过物理校验再计分；奖励总账=-F。独立审计还核对了训练顺序、5步回放的实际奖励和终局标记、检查点哈希、验证选模及冻结推断。', '',
        '## 解释边界','',
        '测试日期编号为5、19、53、55、76，均不在既有使用日期清单中；日期55是一小时，其余是完整半小时。平均改善率先在每个日期内配对，再对五个日期等权平均，避免把窗口长度差异误作性能变化。', '',
        '仅有五个日期和单个固定seed，不能宣称统计显著、任意未知订单均获益或已经收敛。输入保留真实源订单及库存账本，但货架位置为固定合成映射，不能直接等同原工厂部署表现。', '',
        '## 可复现产物','',
        f"最佳模型SHA256：`{result['model_sha256']}`。",'',
        '模型、完整训练记录、冻结验证记录、五日期四策略测试、机器可读审计和逐日期CSV均保存在同一实验目录。使用独立测试后的模型调整必须明确标记探索性，不能继续称这五个日期为未见测试。','']
    def rate_range(value):
        return '未调用GA' if value is None else f'{value[0]:.4f}–{value[1]:.4f}'
    lines+=['','## GA双概率自适应的实际记录','',
        '每代以连续停滞代数s和联合基因多样性d更新：顺序变异率pm=clip(0.7×[1+0.20s+0.60(1−d)],0.05,0.95)，归属变异率=min(0.95,pm+0.1)，交叉率pc=clip(0.9−0.04s−0.20(1−d),0.55,0.95)。两种策略共用这份规则。','',
        'GA动作次数不等于实际搜索次数：动作可复用已缓存计划，只有满足既定重规划条件才启动新搜索。下表按真实搜索日志计数，不把缓存复用虚报为新一轮GA计算。','',
        '| 策略 | GA搜索次数 | 顺序变异率范围 | 归属变异率范围 | 交叉率范围 | 交叉触发/尝试 | 最大单次代理评估 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for strategy,label in (('ga','纯自适应GA'),('dqn','DQN的GA动作')):
        s=result['test_ga_adaptation'][strategy]
        lines.append(f"| {label} | {s['searches']} | {rate_range(s['mutation_range'])} | {rate_range(s['owner_mutation_range'])} | {rate_range(s['crossover_range'])} | {s['crossovers']}/{s['crossover_attempts']} | {s['max_proxy_evaluations_per_search']} |")
    lines+=['','操作触发不必产生不同基因，例如父代相同或归属重新抽到原车辆；交叉触发数不能当作不同候选数。192次代理评估是每次搜索上限，不强制用满。完整逐代日志保留在每个窗口记录中。','']
    lines[0]='# 匈牙利与双概率自适应GA的双动作DQN重训练结果'
    # 只在全部审计通过时写入最终文件；不完整时不会创建带有最终结论的报告。
    write(FOLDER/'aggregate.json',result)
    csv_path=FOLDER/'paired_results.csv'
    doc_path=ROOT/'docs/匈牙利自适应GA-DQN重训练结果.md'
    for path,content in ((csv_path,stream.getvalue()),(doc_path,'\n'.join(lines))):
        if path.exists(): path.read_text(encoding='utf-8')
        path.write_text(content,encoding='utf-8')
    return True

if __name__=='__main__':
    report=analyze()
    published=publish(report)
    print(json.dumps(dict(published=published,training_windows=report['training_windows'],
        completed_validation_epochs=len(report['validation_epochs']),completed_test_dates=report['completed_test_dates'],
        mean_paired_improvement_percent=report['mean_paired_improvement_percent']),ensure_ascii=False,indent=2),flush=True)
