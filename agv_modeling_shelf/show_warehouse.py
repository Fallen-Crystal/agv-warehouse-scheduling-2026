"""在PyCharm右键运行，生成不依赖网络的仓库与实际轨迹查看页面。"""
from pathlib import Path
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from threading import Lock
from model import example
from baseline import run
from optimized import run as optimized_run
from validation import validate
from model import Scenario
from scenario_io import unpack_scene, pack_scene, scenario_id
from batch_experiments import run_batch

TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>仓库地图与车辆轨迹</title>
<style>
:root{font-family:"Microsoft YaHei",sans-serif;color:#243449;background:#edf2f6}*{box-sizing:border-box}body{margin:0}main{max-width:1320px;margin:auto;padding:28px}h1{font-size:28px;margin:0 0 10px}p{line-height:1.7}header p{margin:0 0 22px;color:#526477}.controls{display:flex;gap:16px;align-items:center;flex-wrap:wrap;background:white;padding:18px;border:1px solid #cbd5df}button,select{font:inherit;padding:9px 12px;border:1px solid #94a7b8;background:white;border-radius:5px}button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #dc970f;outline-offset:3px}#play{background:#22679c;color:white}.stage{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:20px;margin-top:20px}.map{background:white;padding:16px;border:1px solid #cbd5df}canvas{width:100%;height:auto;display:block;cursor:crosshair}aside{background:white;padding:20px;border:1px solid #cbd5df}h2{font-size:18px;margin-top:0}.legend div{display:flex;gap:10px;align-items:center;margin:12px 0}.swatch{width:18px;height:18px;display:inline-block;border:1px solid #abbac9}.numbers{font-family:Consolas,monospace}.note{color:#56687b;font-size:14px}.timeline{display:flex;align-items:center;gap:14px;margin-top:14px}input[type=range]{flex:1;min-width:100px}#vehicles{font-size:14px;line-height:1.8}#cell{border-top:1px solid #dce4ea;padding-top:14px;margin-top:16px}@media(max-width:800px){main{padding:16px}.stage{grid-template-columns:1fr}}
</style>
<main><header><h1>仓库地图与车辆轨迹</h1><p>每个方格是一处位置。车辆每步走一格或停留；点击方格查看坐标和可通行的四邻接位置。</p></header>
<div class="controls"><label>场景 <select id="scene"></select></label><button id="play">播放</button><button id="step">下一步</button><button id="reset">回到开始</button><label><input id="trails" type="checkbox" checked> 显示已走轨迹</label></div>
<div class="stage"><section class="map"><canvas id="map" width="1040" height="800" aria-label="仓库货架、通道、车辆及任务位置"></canvas><div class="timeline"><span>时刻</span><input id="time" type="range" min="0" value="0"><output id="timeLabel" class="numbers"></output></div><p id="description" class="note"></p></section>
<aside><h2>看图说明</h2><div class="legend"><div><i class="swatch" style="background:#dfb57a"></i>货架，不可进入</div><div><i class="swatch" style="background:#536576"></i>墙体或边界障碍</div><div><i class="swatch" style="background:#dae9f5"></i>专属停车位 H</div><div><i class="swatch" style="background:#d3eddd"></i>本场景的取货点 P</div><div><i class="swatch" style="background:#ffe7b0"></i>本场景的交付点 D</div><div><i class="swatch" style="background:#fff"></i>可通行地面</div></div><p id="progress"></p><div id="vehicles"></div><p id="cell">点击地图中的格子，查看上下左右能走到哪里。绿色边框只表示地图相邻可通行，不代表当时没有其他车辆占用。</p></aside></div>
<p class="note">这是设定的教学仿真仓库。播放使用环境实际执行的轨迹；可选择距离贪心、最小代价匹配与联合后缀重规划；重规划保留已执行路线和已开始的装卸服务。动态任务只在释放后显示；未来订单不展示。动画按离散步跳转，未模拟实际车身尺寸。</p></main>
<script>
const datasets=__DATA__;
const $=id=>document.getElementById(id), canvas=$('map'), ctx=canvas.getContext('2d');
const colors=['#176ca7','#af4d8b','#bd6819','#16816c','#6752b8','#bd4650','#578023','#3c7f87'];
const names={idle:'停车等待',returning:'返回停车位',to_pickup:'前往取货',loading:'装载',to_delivery:'前往交付',unloading:'卸载'};
let selected=0,t=0,timer=null,hit=null,geometry=null;
datasets.forEach((d,i)=>{const o=document.createElement('option');o.value=i;o.textContent=d.name;$('scene').appendChild(o)});
const key=p=>p.join(','),same=(a,b)=>key(a)===key(b);
function targetShelves(s,r,time){
 const picked=new Set(r.assignments.filter(e=>e.pickup_end<=time).map(e=>e.task_id));
 return new Set(s.tasks.filter(j=>j.release<=time&&j.shelf&&!picked.has(j.id)).map(j=>key(j.shelf)));
}
function stop(){if(timer!==null)clearInterval(timer);timer=null;$('play').textContent='播放'}
function draw(){
 const {scenario:s,result:r}=datasets[selected], cell=Math.min(940/s.width,650/s.height), ox=(1040-cell*s.width)/2,oy=48;
 geometry={cell,ox,oy,s};ctx.clearRect(0,0,1040,800);ctx.font='15px Microsoft YaHei';ctx.textAlign='center';ctx.textBaseline='middle';
 const blocked=new Set(s.blocked.map(key)), shelves=new Set(s.shelves.map(key));
 const visible=s.tasks.filter(j=>j.release<=t), deliveries=new Set(visible.map(j=>key(j.delivery))), targets=targetShelves(s,r,t);
 for(let x=0;x<s.width;x++){ctx.fillStyle='#526477';ctx.fillText(x,ox+(x+.5)*cell,oy-18)}
 for(let y=0;y<s.height;y++){ctx.fillStyle='#526477';ctx.fillText(y,ox-18,oy+(y+.5)*cell)}
 let neighbors=[];
 if(hit&&!blocked.has(key(hit)))neighbors=[[hit[0]+1,hit[1]],[hit[0]-1,hit[1]],[hit[0],hit[1]+1],[hit[0],hit[1]-1]].filter(p=>p[0]>=0&&p[0]<s.width&&p[1]>=0&&p[1]<s.height&&!blocked.has(key(p)));
 for(let y=0;y<s.height;y++)for(let x=0;x<s.width;x++){
  const p=[x,y],k=key(p),home=s.homes.findIndex(q=>same(q,p));
  ctx.fillStyle=shelves.has(k)?'#dfb57a':blocked.has(k)?'#536576':home>=0?'#dae9f5':deliveries.has(k)?'#ffe7b0':'#fff';
  ctx.fillRect(ox+x*cell,oy+y*cell,cell,cell);ctx.strokeStyle='#d1dce5';ctx.lineWidth=1;ctx.strokeRect(ox+x*cell,oy+y*cell,cell,cell);
  ctx.fillStyle='#304253';ctx.font=`${Math.max(12,cell*.3)}px Microsoft YaHei`;
  const label=home>=0?'H'+home:targets.has(k)?'S':deliveries.has(k)?'D':'';
  if(label)ctx.fillText(label,ox+(x+.5)*cell,oy+(y+.5)*cell);
  if(targets.has(k)){ctx.strokeStyle='#cb7d0a';ctx.lineWidth=3;ctx.strokeRect(ox+x*cell+3,oy+y*cell+3,cell-6,cell-6)}
  if(neighbors.some(q=>same(q,p))){ctx.strokeStyle='#18926a';ctx.lineWidth=3;ctx.strokeRect(ox+x*cell+3,oy+y*cell+3,cell-6,cell-6)}
  if(hit&&same(hit,p)){ctx.strokeStyle='#22679c';ctx.lineWidth=3;ctx.strokeRect(ox+x*cell+2,oy+y*cell+2,cell-4,cell-4)}
 }
 if($('trails').checked)r.paths.forEach((path,k)=>{ctx.beginPath();ctx.strokeStyle=colors[k];ctx.globalAlpha=.4;ctx.lineWidth=3;path.slice(0,t+1).forEach((p,i)=>{const x=ox+(p[0]+.5)*cell,y=oy+(p[1]+.5)*cell;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.globalAlpha=1});
 r.assignments.filter(e=>e.assigned_at<=t&&e.pickup_end>t).forEach(e=>{const p=e.pickup_point;ctx.strokeStyle=colors[e.vehicle];ctx.lineWidth=3;ctx.strokeRect(ox+p[0]*cell+4,oy+p[1]*cell+4,cell-8,cell-8)});
 r.paths.forEach((path,k)=>{const p=path[Math.min(t,path.length-1)];ctx.beginPath();ctx.arc(ox+(p[0]+.5)*cell,oy+(p[1]+.5)*cell,cell*.3,0,Math.PI*2);ctx.fillStyle=colors[k];ctx.fill();ctx.fillStyle='#fff';ctx.font=`bold ${Math.max(12,cell*.32)}px Microsoft YaHei`;ctx.fillText(k,ox+(p[0]+.5)*cell,oy+(p[1]+.5)*cell)});
 $('time').value=t;$('timeLabel').textContent=t+' / '+r.time;
 $('progress').textContent='已出现 '+visible.length+' 单 · 已完成 '+r.events.filter(e=>e.delivery_end<=t).length+' 单';
 $('description').textContent=`${s.width}×${s.height} 格 · ${s.homes.length} 辆车 · `+(r.feasible?`最后一单完成于第 ${r.makespan} 步 · 返回结束于第 ${r.time} 步`:`当前只完成 ${r.completed}/${r.total_tasks} 单 · 执行截至第 ${r.time} 步`);
 $('vehicles').replaceChildren();r.paths.forEach((path,k)=>{const line=document.createElement('div');line.style.color=colors[k];const state=t<r.time?r.interval_states[k][t]:'idle';const active=r.assignments.find(e=>e.vehicle===k&&e.assigned_at<=t&&e.delivery_end>t);line.textContent='车 '+k+'：'+names[state]+'，位置 ('+path[t].join(', ')+')'+(active?'，装货停靠 ('+active.pickup_point.join(', ')+')':'');$('vehicles').appendChild(line)});
 if(hit)$('cell').textContent='选中 ('+hit.join(', ')+')。'+(blocked.has(key(hit))?'此格为障碍，车辆不能进入。':'四邻接地面位置：'+(neighbors.map(p=>'('+p.join(', ')+')').join('、')||'无')+'。需要另行检查车辆占用和专属停车位限制。');
}
function load(){stop();selected=Number($('scene').value);t=0;hit=null;$('time').max=datasets[selected].result.time;$('cell').textContent='点击格子查看四邻接。绿色边框只表示地图上可通行，仍需检查车辆占用。';draw()}
$('scene').onchange=load;$('time').oninput=()=>{stop();t=Number($('time').value);draw()};$('reset').onclick=load;$('trails').onchange=draw;
$('step').onclick=()=>{stop();t=Math.min(t+1,datasets[selected].result.time);draw()};
$('play').onclick=()=>{if(timer!==null){stop();return}if(t>=datasets[selected].result.time)t=0;$('play').textContent='暂停';timer=setInterval(()=>{if(t<datasets[selected].result.time){t++;draw()}else stop()},350)};
canvas.onclick=e=>{const box=canvas.getBoundingClientRect(),{ox,oy,cell,s}=geometry;const p=[Math.floor(((e.clientX-box.left)*1040/box.width-ox)/cell),Math.floor(((e.clientY-box.top)*800/box.height-oy)/cell)];if(p[0]>=0&&p[0]<s.width&&p[1]>=0&&p[1]<s.height){hit=p;draw()}};
load();
</script></html>'''


DEFAULTS = dict(size='small', vehicles=4, layout='bottleneck', mode='static',
                arrival='batch', demand='balanced', delivery_pattern='distributed',
                task_count=12, seed=0, horizon=600, algorithm='baseline')


def calculate(options):
    if not isinstance(options, dict) or set(options)-set(DEFAULTS):
        raise ValueError('参数不合法')
    options = {**DEFAULTS, **options}
    for name, minimum, maximum in [('vehicles',1,8),('task_count',0,60),('seed',0,999999),('horizon',60,1800)]:
        if type(options[name]) is not int or not minimum <= options[name] <= maximum:
            raise ValueError(f'{name} 必须是 {minimum} 到 {maximum} 的整数')
    algorithm=options['algorithm']
    if algorithm not in ('baseline','matching_only','joint_only','matching_joint'):
        raise ValueError('未知算法')
    s = example(**{k:v for k,v in options.items() if k!='algorithm'})
    r = run(s) if algorithm=='baseline' else optimized_run(s,assignment='greedy' if algorithm=='joint_only' else 'matching',joint=algorithm!='matching_only')
    validate(s, r)
    return dict(name='自选场景', config=options, scenario=s.to_dict(), result=r,scenario_sha256=scenario_id(s))


def calculate_loaded(data):
    s=unpack_scene(data)
    if any(j.shelf is None for j in s.tasks):
        raise ValueError('新版页面只接受指定货架格的订单；旧固定取货点文件请使用旧版打开。')
    if s.width>30 or s.height>30 or len(s.homes)>8 or len(s.tasks)>60 or s.horizon>1800:
        raise ValueError('页面导入限制：地图不超过30×30、8辆车、60单、1800步')
    algorithm=data.get('config',{}).get('algorithm','baseline') if isinstance(data.get('config'),dict) else 'baseline'
    if algorithm not in ('baseline','matching_only','joint_only','matching_joint'):raise ValueError('未知算法')
    r=run(s) if algorithm=='baseline' else optimized_run(s,assignment='greedy' if algorithm=='joint_only' else 'matching',joint=algorithm!='matching_only')
    validate(s,r)
    return dict(name='导入的固定场景',config=None,scenario=s.to_dict(),result=r,scenario_sha256=scenario_id(s))


def calculate_batch(data):
    if not isinstance(data,dict) or set(data)!={'config','start_seed','count'}:raise ValueError('批量参数不合法')
    start,count=data['start_seed'],data['count']
    if type(start) is not int or type(count) is not int or not 1<=count<=20 or not 0<=start<=999999-count+1:
        raise ValueError('批量数量1～20，起始种子需保证全部种子不超过999999')
    config={**DEFAULTS,**data['config']}
    if set(config)!=set(DEFAULTS):raise ValueError('未知场景参数')
    calculate(config)  # 用单场景入口检查网页参数范围
    algorithm=config.pop('algorithm')
    from optimized import matching_action
    if algorithm=='baseline':return run_batch(config,range(start,start+count))
    solver=lambda scenario: optimized_run(scenario,assignment='greedy' if algorithm=='joint_only' else 'matching',joint=algorithm!='matching_only')
    return run_batch(config,range(start,start+count),policies={algorithm:matching_action},runners={algorithm:solver})


def make_html(initial=None):
    html = TEMPLATE
    controls = '''<div class="controls">
<label>调度算法 <select id="algorithm"><option value="baseline">队友原版：距离贪心</option><option value="matching_only">仅最小代价匹配</option><option value="joint_only">仅联合重规划</option><option value="matching_joint">匹配 + 联合重规划</option></select></label>
<label>仓库大小 <select id="size"><option value="small">小：13×11格</option><option value="medium">中：19×15格</option><option value="large">大：25×19格</option></select></label>
<label>车辆数 <select id="vehiclesCount">'''+''.join(f'<option value="{k}"'+(' selected' if k==4 else '')+f'>{k}辆</option>' for k in range(1,9))+'''</select></label>
<label>通道 <select id="layout"><option value="bottleneck">窄：1个通行口</option><option value="wide">宽：3个通行口</option></select></label>
<label>任务模式 <select id="mode"><option value="static">静态</option><option value="dynamic">动态</option></select></label>
<label>动态订单到达 <select id="arrival"><option value="batch">每15步3单</option><option value="uniform">每5步1单</option><option value="irregular">不规则间隔1～9步</option><option value="burst">每30步6单</option></select></label>
<label>取货位置分布 <select id="demand"><option value="balanced">左、右侧取货概率各50%</option><option value="left_hotspot">每单有80%概率从左侧取货</option><option value="right_hotspot">每单有80%概率从右侧取货</option><option value="switching">前半订单偏左取货，后半偏右</option></select></label>
<label>交付点 <select id="delivery"><option value="distributed">分散交付</option><option value="shared">集中交付</option></select></label>
<label>任务数量 <input id="taskCount" type="number" min="0" max="60" value="12" style="width:75px"></label>
<label>任务种子 <input id="seed" type="number" min="0" max="999999" value="0" style="width:90px"></label>
<label>最大步数 <input id="horizon" type="number" min="60" max="1800" value="600" style="width:90px"></label>
<button id="generate">生成并运行</button></div>
<p id="status" role="status" aria-live="polite"></p>
<div class="controls"><button id="play">播放</button><button id="step">下一步</button><button id="reset">回到开始</button><label><input id="trails" type="checkbox" checked> 显示已走轨迹</label></div>'''
    start = html.index('<div class="controls">')
    end = html.index('<div class="stage">', start)
    html = html[:start]+controls+'\n'+html[end:]
    html = html.replace('const datasets=__DATA__;', 'let datasets=__DATA__;')
    html = html.replace("datasets.forEach((d,i)=>{const o=document.createElement('option');o.value=i;o.textContent=d.name;$('scene').appendChild(o)});", '')
    html = html.replace("selected=Number($('scene').value)", 'selected=0')
    html = html.replace("$('scene').onchange=load;", '')
    html = html.replace('</main>', '''<section class="map" style="margin-top:20px">
<h2>本次运行结果</h2><p id="replanSummary"></p><p class="note">这是生成后整次运行的统计，不随动画时间条变化。时间单位为步，距离单位为格。</p>
<p id="metricScope" role="status"></p><div id="metricSummary"></div>
<h2 style="margin-top:24px">每辆车的工作量</h2><div style="overflow-x:auto"><table id="vehicleMetrics"></table></div>
<p class="note">任务利用率＝执行取送任务的时间占比，不包括空闲返程。工作量不均衡不必然意味着总效率差，应结合响应时间和距离判断。</p>
<button id="exportSummary">下载汇总 CSV</button> <button id="exportVehicles">下载每车 CSV</button> <button id="exportTasks">下载每单 CSV</button>
</section></main>''')
    html = html.replace('</style>', '''
#metricSummary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.metric{background:#edf2f6;padding:14px}.metric strong{display:block;font-size:23px;margin-top:8px}
table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:right;border-bottom:1px solid #dce4ea;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#edf2f6}
</style>''')
    # 结果表仅在加载新结果时刷新，不将完整运行结果伪装成动画当前时刻数据。
    html = html.replace("仍需检查车辆占用。';draw()}", "仍需检查车辆占用。';draw();renderMetrics()}")
    metric_js = r'''
const summaryColumns=[['completed','完成订单'],['total_tasks','总订单'],['completion_rate','完成率'],['comparison_valid','可用于完整比较'],['metrics_scope','统计范围'],['makespan','最后完成时刻'],['time','执行截止时刻'],['mean_flow_time','平均响应时间'],['max_flow_time','最长响应时间'],['p90_flow_time','90%分位响应时间'],['mean_dispatch_wait','平均等派单时间'],['mean_pickup_duration','平均前往取货时间'],['mean_loaded_duration','平均载货运输时间'],['mean_service_duration','平均装卸时间'],['moves','总移动距离'],['empty_moves','空驶距离'],['loaded_moves','载货距离'],['traffic_wait_steps','行驶阶段等待'],['workload_cv','工作量变异系数']];
const vehicleColumns=[['vehicle','车辆'],['assigned_tasks','已指派订单'],['completed_tasks','完成订单'],['moves','移动距离'],['empty_moves','空驶距离'],['loaded_moves','载货距离'],['task_busy_steps','任务执行时间'],['task_utilization','任务利用率'],['service_steps','装卸占位'],['idle_steps','停车空闲'],['traffic_wait_steps','行驶等待']];
const taskColumns=[['task_id','任务'],['vehicle','车辆'],['shelf_x','目标货架横坐标'],['shelf_y','目标货架纵坐标'],['pickup_x','实际装货停靠横坐标'],['pickup_y','实际装货停靠纵坐标'],['release','出现时刻'],['assigned_at','指派时刻'],['completed_at','完成时刻'],['flow_time','订单完成耗时'],['dispatch_wait','等车接单时间'],['pickup_duration','前往取货'],['loaded_duration','载货运输'],['service_duration','装卸服务']];
function formatMetric(value){return value===null||value===undefined?'—':typeof value==='number'?(Number.isInteger(value)?String(value):value.toFixed(2)):String(value)}
function renderMetrics(){
 const r=datasets[selected].result;$('replanSummary').textContent=r.algorithm?`联合重规划调用 ${r.algorithm.replan_calls} 次，接受 ${r.algorithm.accepted_replans} 次。日志随完整结果 JSON 保存。`:'队友原版：接单后保持既定路线。';$('metricScope').textContent=r.comparison_valid?'全部订单完成且车辆已返回，可用于完整场景比较。':`此场景未成功结束。响应时间仅覆盖已完成的 ${r.completed}/${r.total_tasks} 单；不能与成功场景直接比较。`;
 $('metricScope').style.color=r.comparison_valid?'#16816c':'#a44a12';$('metricSummary').replaceChildren();
 const cards=[['完成订单',`${r.completed}/${r.total_tasks}`],['平均响应时间',r.response_sample_count?r.mean_flow_time:(r.total_tasks?null:0)],['最长响应时间',r.max_flow_time],['90%分位响应时间',r.p90_flow_time],['平均等派单时间',r.mean_dispatch_wait],['平均前往取货时间',r.mean_pickup_duration],['平均载货运输时间',r.mean_loaded_duration],['平均装卸时间',r.mean_service_duration],['空驶 / 载货距离',`${r.empty_moves} / ${r.loaded_moves}`],['行驶阶段等待',r.traffic_wait_steps],['工作量变异系数',r.workload_cv]];
 cards.forEach(([label,value])=>{const card=document.createElement('div');card.className='metric';const name=document.createElement('span');name.textContent=label;const number=document.createElement('strong');number.textContent=formatMetric(value);card.appendChild(name);card.appendChild(number);$('metricSummary').appendChild(card)});
 const table=$('vehicleMetrics');table.replaceChildren();const head=document.createElement('tr');vehicleColumns.forEach(([key,label])=>{const th=document.createElement('th');th.textContent=label;head.appendChild(th)});table.appendChild(head);
 r.per_vehicle.forEach(row=>{const tr=document.createElement('tr');vehicleColumns.forEach(([key])=>{const td=document.createElement('td');td.textContent=key==='task_utilization'?(100*row[key]).toFixed(1)+'%':formatMetric(row[key]);tr.appendChild(td)});table.appendChild(tr)});
}
function downloadCSV(name,columns,rows){
 const escape=value=>'"'+String(value===null||value===undefined?'':value).replace(/"/g,'""')+'"';
 const csv='\ufeff'+[columns.map(c=>escape(c[1])).join(','),...rows.map(row=>columns.map(c=>escape(row[c[0]])).join(','))].join('\r\n');
 const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('exportSummary').onclick=()=>{const entry=datasets[selected],c=entry.config||{},r=entry.result,s=entry.scenario;downloadCSV('仓库运行汇总.csv',[['scenario_sha256','场景校验值'],['width','地图宽度（格）'],['height','地图高度（格）'],['size','仓库大小'],['vehicles','车辆数'],['layout','通道'],['mode','任务模式'],['arrival','到达方式'],['demand','取货需求'],['delivery_pattern','交付分布'],['task_count','任务数量'],['seed','任务种子'],['horizon','最大步数'],...summaryColumns],[{...c,...r,scenario_sha256:entry.scenario_sha256,width:s.width,height:s.height,vehicles:s.homes.length,task_count:s.tasks.length,horizon:s.horizon}])};
$('exportVehicles').onclick=()=>downloadCSV('每辆车工作量.csv',vehicleColumns,datasets[selected].result.per_vehicle);
$('exportTasks').onclick=()=>downloadCSV('每单响应时间.csv',taskColumns,datasets[selected].result.task_metrics);
'''
    html = html.replace('load();\n</script>', metric_js+'\nload();\n</script>')
    html = html.replace('load();\n</script>', r'''
function controls(){return {size:$('size').value,vehicles:Number($('vehiclesCount').value),layout:$('layout').value,
 mode:$('mode').value,arrival:$('arrival').value,demand:$('demand').value,delivery_pattern:$('delivery').value,
 task_count:Number($('taskCount').value),seed:Number($('seed').value),horizon:Number($('horizon').value),algorithm:$('algorithm').value}}
function updateMode(){$('arrival').disabled=$('mode').value==='static'}
function markChanged(){updateMode();$('status').textContent='参数已修改。点击“生成并运行”应用新设置；当前地图仍是上次结果。'}
['algorithm','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon'].forEach(id=>$(id).onchange=markChanged);
$('generate').onclick=async()=>{
 if(location.protocol==='file:'){$('status').textContent='自由组合需要先在 PyCharm 运行 show_warehouse.py，再使用自动打开的页面。这个离线文件只能查看保存的默认结果。';return}
 stop();$('generate').disabled=true;
 const settings=['algorithm','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon'];
 settings.forEach(id=>$(id).disabled=true);$('status').textContent='正在生成任务并计算车辆路线…';
 try{
  const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(controls())});
  const payload=await response.json();if(!response.ok)throw new Error(payload.error||'运行失败');
  datasets=[payload];load();const c=payload.config,r=payload.result;
  $('status').textContent=(r.feasible?'运行完成。':'未在最大步数内全部完成并返回。')+' 当前：'+$('size').selectedOptions[0].textContent+'，'+c.vehicles+'辆车，'+$('layout').selectedOptions[0].textContent+'，'+$('mode').selectedOptions[0].textContent+'。订单 '+c.task_count+' 单，完成 '+r.completed+' 单。'+(c.mode==='static'?'所有任务在第0步出现。':'到达方式：'+$('arrival').selectedOptions[0].textContent+'。');
 }catch(error){$('status').textContent='无法生成：'+error.message+'。请确认 PyCharm 中 show_warehouse.py 仍在运行。'}
 finally{$('generate').disabled=false;settings.forEach(id=>$(id).disabled=false);updateMode()}
};
updateMode();load();
$('status').textContent=location.protocol==='file:'?'当前是保存的默认结果。自由组合请在 PyCharm 运行 show_warehouse.py。':'各项可以独立选择。修改后点击“生成并运行”，再播放车辆轨迹。';
</script>''')
    html = html.replace('90%分位响应时间','90%订单的耗时上限')
    html = html.replace('<div id="metricSummary"></div>', '<div id="metricSummary"></div><p class="note">90%订单的耗时上限：本次已完成订单中，至少90%的订单从出现到完成不超过这个时长。行驶阶段等待：车辆在取送或返回途中原地停留，排除装卸和停车空闲；多车等待步数相加。工作量变异系数：各车任务执行时间的不均衡程度，0表示一样多，数值越大越不均衡。</p>')
    html = html.replace('行驶阶段等待','途中等待总步数').replace('工作量变异系数','车辆工作量差异')
    html = html.replace("['traffic_wait_steps','行驶等待']", "['traffic_wait_steps','途中等待步数']")
    html=html.replace('<h1>仓库地图与车辆轨迹</h1>','<h1>基础版：场景复现与批量实验</h1>')
    tools='''<section class="map" style="margin-top:20px"><h2>保存和重跑同一个场景</h2>
<button id="saveScene">下载完整场景与结果 JSON</button>
<label>选择保存的场景 <input id="sceneFile" type="file" accept=".json,application/json"></label><button id="loadScene">读取场景并重新运行</button>
<p class="note">导入使用文件里的实际地图和订单，不使用当前下拉选项重新生成。再次点击“生成并运行”则会使用下拉选项创建新场景。</p>
<h2>批量运行多个任务种子</h2><label>起始种子 <input id="batchSeed" type="number" min="0" max="999999" value="0" style="width:90px"></label>
<label>运行数量 <input id="batchCount" type="number" min="1" max="20" value="5" style="width:75px"></label>
<button id="runBatch">按当前参数批量运行</button><button id="downloadBatch" disabled>下载批量完整结果 JSON</button><button id="downloadBatchCSV" disabled>下载批量统计 CSV</button>
<p id="batchStatus" role="status"></p><div id="batchSummary"></div></section>'''
    html=html.replace('<div class="stage">',tools+'<div class="stage">')
    html=html.replace('<h2>本次运行结果</h2><p id="replanSummary"></p>','<h2>本次运行结果</h2><p id="replanSummary"></p><h3>失败与未完成记录</h3><div id="failureSummary"></div><button id="exportFailures">下载失败记录 JSON</button>')
    html=html.replace('function renderMetrics(){','function renderMetrics(){\n renderFailures();')
    js=r'''
let batchReport=null;
function downloadJSON(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function renderFailures(){const r=datasets[selected].result,d=r.diagnostics;$('failureSummary').replaceChildren();if(!d)return;
 const text=document.createElement('p');text.textContent=`规划尝试失败 ${d.planning_failure_count} 次（取货 ${d.planning_failure_by_leg.pickup}、交付 ${d.planning_failure_by_leg.delivery}、返程 ${d.planning_failure_by_leg.return}）；未完成订单 ${d.unfinished_tasks.length} 单；未回停车位 ${d.vehicles_away_from_home.length} 辆。`; $('failureSummary').appendChild(text);
 if(d.execution_error){const line=document.createElement('p');line.textContent='策略执行错误：'+d.execution_error.type+' '+d.execution_error.message;$('failureSummary').appendChild(line)}
 const labels={not_released:'尚未出现',waiting_assignment:'等待派单',executing:'正在执行'};
 d.unfinished_tasks.forEach(j=>{const line=document.createElement('p');line.textContent='任务 '+j.task_id+'：'+labels[j.status]+'，出现后已过 '+j.elapsed_since_release+' 步，规划失败 '+j.planning_failures+' 次。';$('failureSummary').appendChild(line)});
 const note=document.createElement('p');note.className='note';note.textContent=d.note;$('failureSummary').appendChild(note);
}
function online(){if(location.protocol==='file:')throw new Error('请先在PyCharm运行 show_warehouse.py，使用自动打开的本机页面')}
async function send(path,data){online();const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result}
function locked(value){['algorithm','generate','loadScene','runBatch','sceneFile','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon','batchSeed','batchCount'].forEach(id=>$(id).disabled=value);if(!value)updateMode()}
$('saveScene').onclick=()=>{const e=datasets[selected];downloadJSON('完整仓库场景.json',{format:'agv-scene-v1',scenario:e.scenario,scenario_sha256:e.scenario_sha256,config:e.config,result:e.result})};
$('exportFailures').onclick=()=>downloadJSON('失败与未完成记录.json',datasets[selected].result.diagnostics);
$('loadScene').onclick=async()=>{try{const file=$('sceneFile').files[0];if(!file)throw new Error('请先选择JSON文件');if(file.size>10*1024*1024)throw new Error('文件不能超过10MB');online();stop();locked(true);$('status').textContent='正在读取并重新运行固定场景…';const payload=await send('/api/load',JSON.parse(await file.text()));datasets=[payload];load();$('status').textContent='已按文件中的实际地图和任务重新运行。场景校验值：'+payload.scenario_sha256.slice(0,12)+'。当前下拉选项不代表导入文件。'}catch(error){$('status').textContent=error.message}finally{locked(false)}};
$('runBatch').onclick=async()=>{try{online();stop();const options=controls();const start_seed=Number($('batchSeed').value),count=Number($('batchCount').value);locked(true);$('batchStatus').textContent='正在批量运行，请保持Python服务开启…';batchReport=await send('/api/batch',{config:options,start_seed,count});const s=batchReport.summaries[0];$('batchStatus').textContent=`运行 ${s.runs} 次，成功 ${s.successes} 次，失败 ${s.failures} 次，成功率 ${(s.success_rate*100).toFixed(1)}%。统计成绩只覆盖成功运行，批量实验不改变上面的单场景地图。`;
 $('batchSummary').textContent='成功运行的平均响应时间：'+formatMetric(s.mean_flow_time_mean)+'；样本标准差：'+formatMetric(s.mean_flow_time_std)+'。只成功一次时不计算标准差。';$('downloadBatch').disabled=false;$('downloadBatchCSV').disabled=false;
 }catch(error){$('batchStatus').textContent=error.message}finally{locked(false)}};
$('downloadBatch').onclick=()=>downloadJSON('批量实验完整结果.json',batchReport);
$('downloadBatchCSV').onclick=()=>{if(!batchReport)return;const labels={policy:'策略',runs:'运行数',successes:'成功数',failures:'失败数',success_rate:'成功率',mean_completion_rate:'平均完成率'};const fields={makespan:'任务完成时刻',mean_flow_time:'响应时间',max_flow_time:'最长响应',p90_flow_time:'90%订单耗时上限',moves:'移动距离',empty_moves:'空驶距离',loaded_moves:'载货距离'};Object.entries(fields).forEach(([key,label])=>{labels[key+'_mean']='成功样本平均'+label;labels[key+'_std']='成功样本'+label+'标准差'});downloadCSV('批量实验统计.csv',Object.keys(batchReport.summaries[0]).map(k=>[k,labels[k]||k]),batchReport.summaries)};
'''
    html=html.replace('updateMode();load();',js+'\nupdateMode();load();')
    html=html.replace("const labels={policy:'策略',runs:","const labels={scenario_config:'公共场景参数',task_seeds:'任务种子列表',policy:'策略',runs:")
    html=html.replace("settings.forEach(id=>$(id).disabled=true)","locked(true)")
    html=html.replace("settings.forEach(id=>$(id).disabled=false);updateMode()","locked(false)")
    html=html.replace('平均响应时间','平均订单完成耗时').replace('平均等派单时间','平均等车接单时间')
    html=html.replace('最大步数','整次仿真允许运行的最长时间（步）')
    html=html.replace('基础版：场景复现与批量实验','货架取货版：车辆选择停靠侧')
    html=html.replace('<div><i class="swatch" style="background:#d3eddd"></i>本场景的取货点 P</div>', '<div><i class="swatch" style="background:#dfb57a"></i>当前待取货的货架格 S</div><div><i class="swatch" style="background:white;border:3px solid #176ca7"></i>车辆计划装货停靠格</div>')
    html=html.replace('动态任务只在释放后显示；未来订单不展示。','动态任务只在释放后显示；未来订单不展示。每个货架小格都可成为订单目标，单个订单的目标不会移动。S只标记已出现且尚未装货完成的订单目标；该格对应订单全部取完后取消标记。车辆颜色边框标记当前计划装货的停靠格。')
    html=html.replace('agv-scene-v1','agv-scene-v2')
    html=html.replace('每个方格是一处位置。','每个货架小格是一处储货位置。S标出订单要取货的货架格，车辆从旁边合法格停靠取货。大仓库有四列货架。')
    html=html.replace("['demand','取货需求']","['demand','取货位置分布']")
    html=html.replace('<p id="status" role="status" aria-live="polite"></p>', '<p class="note">取货位置分布决定订单来自哪一侧货架。80%是每单的生成概率，不保证一小批订单恰好占80%；前半偏左、后半偏右分别使用80%的左侧、右侧取货概率。</p><p id="status" role="status" aria-live="polite"></p>')
    html=html.replace("mean_flow_time:'响应时间'","mean_flow_time:'订单完成耗时'")
    html=html.replace("const name=document.createElement('span');name.textContent=label;", "const name=document.createElement('span');name.textContent=label;const explanations={'平均订单完成耗时':'订单出现 → 卸货完成，包含等车接单时间','平均等车接单时间':'订单出现 → 成功分配给车辆'};if(explanations[label]){card.title=explanations[label];const hint=document.createElement('div');hint.className='note';hint.textContent=explanations[label];card.appendChild(hint);}")
    return html.replace('__DATA__', json.dumps([initial or calculate({})], ensure_ascii=False).replace('</', r'<\/'))


def build_viewer(open_browser=False):
    destination = Path(__file__).resolve().parent/'仓库地图与轨迹.html'
    destination.write_text(make_html(), encoding='utf-8')
    if open_browser:
        webbrowser.open(destination.as_uri())
    return destination


def create_server():
    # 本机页面只提供固定路由和模型计算，不提供任意目录文件浏览。
    html = make_html().encode('utf-8')
    cache = {}
    lock = Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, kind='application/json; charset=utf-8'):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self.send(200, html, 'text/html; charset=utf-8')
            else:
                self.send(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.path not in ('/api/run','/api/load','/api/batch'):
                self.send(404, b'{"error":"not found"}'); return
            # 拒绝其他网页跨来源调用，本机UI只与自身服务通信。
            origin = self.headers.get('Origin')
            if origin and origin != 'http://'+self.headers.get('Host',''):
                self.send(403, b'{"error":"origin rejected"}'); return
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                self.send(415, b'{"error":"expected application/json"}'); return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= (10*1024*1024 if self.path=='/api/load' else 4096):
                    raise ValueError('请求长度不合法')
                options = json.loads(self.rfile.read(length))
                signature = self.path+json.dumps(options, sort_keys=True)
                with lock:
                    if signature not in cache:
                        entry = calculate_loaded(options) if self.path=='/api/load' else calculate_batch(options) if self.path=='/api/batch' else calculate(options)
                        if len(cache) >= 32:
                            cache.pop(next(iter(cache)))
                        cache[signature] = json.dumps(entry, ensure_ascii=False).encode('utf-8')
                    body = cache[signature]
                self.send(200, body)
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, json.dumps(dict(error=str(error)), ensure_ascii=False).encode('utf-8'))
    return ThreadingHTTPServer(('127.0.0.1',0), Handler)


def main():
    build_viewer()
    server = create_server()
    url = f'http://127.0.0.1:{server.server_port}/'
    print('仓库查看页面：'+url)
    print('请保持本程序运行，在页面中选择参数并点击“生成并运行”。关闭服务请在PyCharm点击停止。')
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
