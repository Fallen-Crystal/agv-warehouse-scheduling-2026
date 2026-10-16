
let datasets=JSON.parse(document.getElementById('scene-data').textContent);
const $=id=>document.getElementById(id), canvas=$('map'), ctx=canvas.getContext('2d');
const colors=['#176ca7','#af4d8b','#bd6819','#16816c','#6752b8','#bd4650','#578023','#3c7f87','#915c48','#7045a1'];
const names={idle:'停车等待',standby:'有限待命',returning:'返回停车位',to_pickup:'前往取货',loading:'装载',to_delivery:'前往交付',unloading:'卸载'};
let selected=0,t=0,timer=null,hit=null,geometry=null;

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
 const visible=s.tasks.filter(j=>j.release<=t), deliveries=new Set((s.stations||visible.map(j=>j.delivery)).map(key)), targets=targetShelves(s,r,t);
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
 $('pendingOrders').replaceChildren();const assigned=new Set(r.assignments.filter(e=>e.assigned_at<=t).map(e=>e.task_id));visible.filter(j=>!assigned.has(j.id)).forEach(j=>{const row=document.createElement('p');const sameFace=['math-v4-integrated','mixed-v9'].includes(s.map_info?.model_version)&&j.shelf&&r.assignments.some(e=>e.assigned_at<=t&&e.pickup_end>t&&e.shelf&&same(e.shelf,j.shelf));row.textContent=`任务 ${j.id} · 出现 ${j.release} · `+(j.shelf?`货架 (${j.shelf.join(',')})`:`取货点 (${j.pickup.join(',')})`)+(s.map_info?` · 第${j.shelf_level}层 · 装货${j.pickup_service}步`:'')+(sameFace?' · 同面取货尚未释放':'');$('pendingOrders').appendChild(row)});
 if(hit)$('cell').textContent='选中 ('+hit.join(', ')+')。'+(blocked.has(key(hit))?'此格为障碍，车辆不能进入。':'四邻接地面位置：'+(neighbors.map(p=>'('+p.join(', ')+')').join('、')||'无')+'。需要另行检查车辆占用和专属停车位限制。');
 if(hit&&s.map_info?.model_version==='mixed-v9'&&s.map_info?.rack_catalog){const bay=s.map_info.rack_catalog.find(row=>same(row.position,hit));if(bay){const points=bay.loading_points||[];$('cell').textContent=`货位 ${bay.bay_id}，${bay.rack_type==='single'?'单排1层，两侧共享一把锁':'独立货架排，最多'+bay.levels+'层'}。合法装货位置：${points.map(q=>'('+q.join(', ')+')').join('、')}。货架实体不可进入。`;}}

}
function load(){stop();selected=0;t=0;hit=null;$('time').max=datasets[selected].result.time;$('cell').textContent='点击格子查看四邻接。绿色边框只表示地图上可通行，仍需检查车辆占用。';draw();renderMetrics()}
$('time').oninput=()=>{stop();t=Number($('time').value);draw()};$('reset').onclick=load;$('trails').onchange=draw;
$('step').onclick=()=>{stop();t=Math.min(t+1,datasets[selected].result.time);draw()};
$('play').onclick=()=>{if(timer!==null){stop();return}if(t>=datasets[selected].result.time)t=0;$('play').textContent='暂停';timer=setInterval(()=>{if(t<datasets[selected].result.time){t++;draw()}else stop()},350)};
canvas.onclick=e=>{const box=canvas.getBoundingClientRect(),{ox,oy,cell,s}=geometry;const p=[Math.floor(((e.clientX-box.left)*1040/box.width-ox)/cell),Math.floor(((e.clientY-box.top)*800/box.height-oy)/cell)];if(p[0]>=0&&p[0]<s.width&&p[1]>=0&&p[1]<s.height){hit=p;draw()}};

const summaryColumns=[['weighted_score','综合分数F'],['score_valid','分数有效'],['normalized_time','T/Tref'],['normalized_response','R/Rref'],['normalized_distance','D/Dref'],['completed','完成订单'],['total_tasks','总订单'],['completion_rate','完成率'],['comparison_valid','可用于完整比较'],['metrics_scope','统计范围'],['makespan','最后完成时刻'],['time','执行截止时刻'],['mean_flow_time','平均订单完成耗时'],['max_flow_time','最长响应时间'],['p90_flow_time','90%订单的耗时上限'],['mean_dispatch_wait','平均等车接单时间'],['mean_pickup_duration','平均前往取货时间'],['mean_loaded_duration','平均载货运输时间'],['mean_service_duration','平均装卸时间'],['moves','总移动距离'],['empty_moves','空驶距离'],['loaded_moves','载货距离'],['traffic_wait_steps','途中等待总步数'],['standby_steps','原地待命步数'],['workload_cv','车辆工作量差异']];
const vehicleColumns=[['vehicle','车辆'],['assigned_tasks','已指派订单'],['completed_tasks','完成订单'],['moves','移动距离'],['empty_moves','空驶距离'],['loaded_moves','载货距离'],['task_busy_steps','任务执行时间'],['task_utilization','任务利用率'],['service_steps','装卸占位'],['idle_steps','停车空闲'],['traffic_wait_steps','途中等待步数']];
const taskColumns=[['shelf_level','货架层号'],['rack_bay','货位编号'],['storage_id','储位编号'],['task_id','任务'],['vehicle','车辆'],['shelf_x','目标货架横坐标'],['shelf_y','目标货架纵坐标'],['pickup_x','实际装货停靠横坐标'],['pickup_y','实际装货停靠纵坐标'],['release','出现时刻'],['assigned_at','指派时刻'],['completed_at','完成时刻'],['flow_time','订单完成耗时'],['dispatch_wait','等车接单时间'],['pickup_duration','前往取货'],['loaded_duration','载货运输'],['service_duration','装卸服务']];
function formatMetric(value){return value===null||value===undefined?'—':typeof value==='number'?(Number.isInteger(value)?String(value):value.toFixed(2)):String(value)}
function renderMetrics(){
 renderFailures();
 const r=datasets[selected].result;$('replanSummary').textContent=r.dispatch_stats?`派单搜索 ${r.dispatch_stats.searched} 次，改变保底批次 ${r.dispatch_stats.changed} 次，影子试算 ${r.dispatch_stats.shadow_calls} 次；逐候选解释随完整 JSON 保存。`:r.algorithm?`联合重规划调用 ${r.algorithm.replan_calls} 次，接受 ${r.algorithm.accepted_replans} 次。日志随完整结果 JSON 保存。`:'队友原版：接单后保持既定路线。';$('metricScope').textContent=r.comparison_valid?'全部订单完成且车辆已返回，可用于完整场景比较。':`此场景未成功结束。响应时间仅覆盖已完成的 ${r.completed}/${r.total_tasks} 单；不能与成功场景直接比较。`;
 $('metricScope').style.color=r.comparison_valid?'#16816c':'#a44a12';$('metricSummary').replaceChildren();
 const cards=[...(r.model_version? [['综合分数 F',r.weighted_score],['归一化 T / R / D',`${formatMetric(r.normalized_time)} / ${formatMetric(r.normalized_response)} / ${formatMetric(r.normalized_distance)}`]]:[]),['完成订单',`${r.completed}/${r.total_tasks}`],['平均订单完成耗时',r.response_sample_count?r.mean_flow_time:(r.total_tasks?null:0)],['最长响应时间',r.max_flow_time],['90%订单的耗时上限',r.p90_flow_time],['平均等车接单时间',r.mean_dispatch_wait],['平均前往取货时间',r.mean_pickup_duration],['平均载货运输时间',r.mean_loaded_duration],['平均装卸时间',r.mean_service_duration],['空驶 / 载货距离',`${r.empty_moves} / ${r.loaded_moves}`],['途中等待总步数',r.traffic_wait_steps],['车辆工作量差异',r.workload_cv]];
 cards.forEach(([label,value])=>{const card=document.createElement('div');card.className='metric';const name=document.createElement('span');name.textContent=label;const explanations={'平均订单完成耗时':'订单出现 → 卸货完成，包含等车接单时间','平均等车接单时间':'订单出现 → 成功分配给车辆'};if(explanations[label]){card.title=explanations[label];const hint=document.createElement('div');hint.className='note';hint.textContent=explanations[label];card.appendChild(hint);}const number=document.createElement('strong');number.textContent=formatMetric(value);card.appendChild(name);card.appendChild(number);$('metricSummary').appendChild(card)});
 const table=$('vehicleMetrics');table.replaceChildren();const head=document.createElement('tr');vehicleColumns.forEach(([key,label])=>{const th=document.createElement('th');th.textContent=label;head.appendChild(th)});table.appendChild(head);
 r.per_vehicle.forEach(row=>{const tr=document.createElement('tr');vehicleColumns.forEach(([key])=>{const td=document.createElement('td');td.textContent=key==='task_utilization'?(100*row[key]).toFixed(1)+'%':formatMetric(row[key]);tr.appendChild(td)});table.appendChild(tr)});
}
function downloadCSV(name,columns,rows){
 const escape=value=>'"'+String(value===null||value===undefined?'':value).replace(/"/g,'""')+'"';
 const csv='\ufeff'+[columns.map(c=>escape(c[1])).join(','),...rows.map(row=>columns.map(c=>escape(row[c[0]])).join(','))].join('\r\n');
 const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('exportSummary').onclick=()=>{const entry=datasets[selected],c=entry.config||{},r=entry.result,s=entry.scenario;downloadCSV('仓库运行汇总.csv',[['scenario_sha256','场景校验值'],['width','地图宽度（格）'],['height','地图高度（格）'],['size','仓库大小'],['vehicles','车辆数'],['layout','通道'],['mode','任务模式'],['arrival','到达方式'],['demand','取货位置分布'],['delivery_pattern','交付分布'],['task_count','任务数量'],['seed','任务种子'],['horizon','整次仿真允许运行的最长时间（步）'],...summaryColumns],[{...c,...r,scenario_sha256:entry.scenario_sha256,width:s.width,height:s.height,vehicles:s.homes.length,task_count:s.tasks.length,horizon:s.horizon}])};
$('exportVehicles').onclick=()=>downloadCSV('每辆车工作量.csv',vehicleColumns,datasets[selected].result.per_vehicle);
$('exportTasks').onclick=()=>downloadCSV('每单响应时间.csv',taskColumns,datasets[selected].result.task_metrics);


function controls(){return {profile:$('profile').value,shelf_layers:Number($('shelfLayers').value),work_width:Number($('workWidth').value),obstacle_layout:$('obstacles').value,layout_variant:0,size:$('size').value,vehicles:Number($('vehiclesCount').value),layout:$('layout').value,
 mode:$('mode').value,arrival:$('arrival').value,demand:$('demand').value,delivery_pattern:$('delivery').value,
 task_count:Number($('taskCount').value),seed:Number($('seed').value),horizon:Number($('horizon').value),algorithm:$('algorithm').value}}
function updateMode(){
 $('arrival').disabled=$('mode').value==='static';
 const profile=$('profile').value, layered=profile!=='legacy', v9=profile==='v9';
 $('layout').disabled=layered;['shelfLayers','workWidth','obstacles'].forEach(id=>$(id).disabled=!layered);
 $('shelfLayers').min=v9?'3':'1';$('shelfLayers').max=v9?'8':'5';
 if(Number($('shelfLayers').value)<Number($('shelfLayers').min)||Number($('shelfLayers').value)>Number($('shelfLayers').max))$('shelfLayers').value='3';
 for(const option of $('size').options)option.disabled=(v9&&option.value==='small')||(!layered&&['xlarge','xxlarge'].includes(option.value));
 if(v9&&$('size').value==='small')$('size').value='medium';
 if(!layered&&['xlarge','xxlarge'].includes($('size').value))$('size').value='large';
 for(const option of $('vehiclesCount').options)option.disabled=!layered&&Number(option.value)>8;
 if(!layered&&Number($('vehiclesCount').value)>8)$('vehiclesCount').value='8';
 if(v9){$('obstacles').value='columns_equipment';$('obstacles').disabled=true;}
 for(const option of $('algorithm').options)option.disabled=option.value.includes('standby')&&!v9;
 if(!v9&&$('algorithm').value.includes('standby'))$('algorithm').value='sipp_greedy_dispatch';
}
function markChanged(){updateMode();$('status').textContent='参数已修改。点击“生成并运行”应用新设置；当前地图仍是上次结果。'}
['profile','shelfLayers','workWidth','obstacles','algorithm','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon'].forEach(id=>$(id).onchange=markChanged);
$('generate').onclick=async()=>{
 if(location.protocol==='file:'){$('status').textContent='自由组合需要先在 终端运行 agv serve，再使用自动打开的页面。这个离线文件只能查看保存的默认结果。';return}
 stop();$('generate').disabled=true;
 const settings=['profile','shelfLayers','workWidth','obstacles','algorithm','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon'];
 locked(true);$('status').textContent='正在生成任务并计算车辆路线…';
 try{
  const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(controls())});
  const payload=await response.json();if(!response.ok)throw new Error(payload.error||'运行失败');
  datasets=[payload];load();const c=payload.config,r=payload.result;
  $('status').textContent=(r.feasible?'运行完成。':'未在整次仿真允许运行的最长时间（步）内全部完成并返回。')+' 当前：'+$('size').selectedOptions[0].textContent+'，'+c.vehicles+'辆车，'+(c.profile!=='legacy'?`${c.profile.toUpperCase()}作业通道宽${c.work_width}格`:$('layout').selectedOptions[0].textContent)+'，'+$('mode').selectedOptions[0].textContent+'。订单 '+c.task_count+' 单，完成 '+r.completed+' 单。'+(c.mode==='static'?'所有任务在第0步出现。':'到达方式：'+$('arrival').selectedOptions[0].textContent+'。');
 }catch(error){$('status').textContent='无法生成：'+error.message+'。请确认 终端中 agv serve 仍在运行。'}
 finally{$('generate').disabled=false;locked(false)}
};

let batchReport=null;
function downloadJSON(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function renderFailures(){const r=datasets[selected].result,d=r.diagnostics;$('failureSummary').replaceChildren();if(!d)return;
 const text=document.createElement('p');text.textContent=`规划尝试失败 ${d.planning_failure_count} 次（取货 ${d.planning_failure_by_leg.pickup}、交付 ${d.planning_failure_by_leg.delivery}、返程 ${d.planning_failure_by_leg.return}）；未完成订单 ${d.unfinished_tasks.length} 单；未回停车位 ${d.vehicles_away_from_home.length} 辆。`; $('failureSummary').appendChild(text);
 if(d.execution_error){const line=document.createElement('p');line.textContent='策略执行错误：'+d.execution_error.type+' '+d.execution_error.message;$('failureSummary').appendChild(line)}
 const labels={not_released:'尚未出现',waiting_assignment:'等待派单',executing:'正在执行'};
 d.unfinished_tasks.forEach(j=>{const line=document.createElement('p');line.textContent='任务 '+j.task_id+'：'+labels[j.status]+'，出现后已过 '+j.elapsed_since_release+' 步，规划失败 '+j.planning_failures+' 次。';$('failureSummary').appendChild(line)});
 const note=document.createElement('p');note.className='note';note.textContent=d.note;$('failureSummary').appendChild(note);
}
function online(){if(location.protocol==='file:')throw new Error('请先在终端运行 agv serve，使用自动打开的本机页面')}
async function send(path,data){online();const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result}
function locked(value){['profile','shelfLayers','workWidth','obstacles','algorithm','generate','loadScene','runBatch','sceneFile','size','vehiclesCount','layout','mode','arrival','demand','delivery','taskCount','seed','horizon','batchSeed','batchCount'].forEach(id=>$(id).disabled=value);if(!value)updateMode()}
$('saveScene').onclick=()=>{const e=datasets[selected];downloadJSON('完整仓库场景.json',{format:e.scenario.map_info?.model_version==='mixed-v9'?'agv-scene-v9':e.scenario.map_info?'agv-scene-v4':'agv-scene-v2',scenario:e.scenario,scenario_sha256:e.scenario_sha256,config:e.config,result:e.result})};
$('exportFailures').onclick=()=>downloadJSON('失败与未完成记录.json',datasets[selected].result.diagnostics);
$('loadScene').onclick=async()=>{try{const file=$('sceneFile').files[0];if(!file)throw new Error('请先选择JSON文件');if(file.size>10*1024*1024)throw new Error('文件不能超过10MB');online();stop();locked(true);$('status').textContent='正在读取并重新运行固定场景…';const payload=await send('/api/load',JSON.parse(await file.text()));datasets=[payload];load();$('status').textContent='已按文件中的实际地图和任务重新运行。场景校验值：'+payload.scenario_sha256.slice(0,12)+'。当前下拉选项不代表导入文件。'}catch(error){$('status').textContent=error.message}finally{locked(false)}};
$('runBatch').onclick=async()=>{try{online();stop();const options=controls();const start_seed=Number($('batchSeed').value),count=Number($('batchCount').value);locked(true);$('batchStatus').textContent='正在批量运行，请保持Python服务开启…';batchReport=await send('/api/batch',{config:options,start_seed,count});const s=batchReport.summaries[0];$('batchStatus').textContent=`运行 ${s.runs} 次，成功 ${s.successes} 次，失败 ${s.failures} 次，成功率 ${(s.success_rate*100).toFixed(1)}%。统计成绩只覆盖成功运行，批量实验不改变上面的单场景地图。`;
 $('batchSummary').textContent='成功运行的平均订单完成耗时：'+formatMetric(s.mean_flow_time_mean)+'；样本标准差：'+formatMetric(s.mean_flow_time_std)+'。只成功一次时不计算标准差。';$('downloadBatch').disabled=false;$('downloadBatchCSV').disabled=false;
 }catch(error){$('batchStatus').textContent=error.message}finally{locked(false)}};
$('downloadBatch').onclick=()=>downloadJSON('批量实验完整结果.json',batchReport);
$('downloadBatchCSV').onclick=()=>{if(!batchReport)return;const labels={scenario_config:'公共场景参数',task_seeds:'任务种子列表',policy:'策略',runs:'运行数',successes:'成功数',failures:'失败数',success_rate:'成功率',mean_completion_rate:'平均完成率'};const fields={makespan:'任务完成时刻',mean_flow_time:'订单完成耗时',max_flow_time:'最长响应',p90_flow_time:'90%订单耗时上限',moves:'移动距离',empty_moves:'空驶距离',loaded_moves:'载货距离'};Object.entries(fields).forEach(([key,label])=>{labels[key+'_mean']='成功样本平均'+label;labels[key+'_std']='成功样本'+label+'标准差'});downloadCSV('批量实验统计.csv',Object.keys(batchReport.summaries[0]).map(k=>[k,labels[k]||k]),batchReport.summaries)};

updateMode();load();
$('status').textContent=location.protocol==='file:'?'当前是保存的默认结果。自由组合请在 终端运行 agv serve。':'各项可以独立选择。修改后点击“生成并运行”，再播放车辆轨迹。';
