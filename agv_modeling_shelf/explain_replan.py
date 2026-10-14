"""Create an offline comparison of one actual accepted busy-route replan."""
import json
from pathlib import Path

PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>途中联合重规划：真实路线解释</title>
<style>body{font:16px system-ui;color:#263443;max-width:1200px;margin:24px auto;padding:16px}h1{font-size:26px}.pair{display:flex;gap:24px;flex-wrap:wrap}.pair>section{flex:1;min-width:340px}canvas{width:100%;border:1px solid #ddd}button,input{font:inherit;padding:8px}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}p{line-height:1.7}</style>
<h1>行驶途中，多辆车一起重新协商剩余路线</h1><p id="summary"></p>
<button id="step">下一步</button><button id="reset">回到重规划时刻</button>
<input id="time" type="range" value="0" min="0"><span id="label"></span>
<div class="pair"><section><h2>修改前的预约</h2><canvas id="before" width="570" height="460"></canvas></section><section><h2>修改后的预约</h2><canvas id="after" width="570" height="460"></canvas></section></div>
<h2>各车的预计卸货完成时间</h2><table><thead><tr><th>车辆</th><th>重规划时状态</th><th>修改前</th><th>修改后</th></tr></thead><tbody id="rows"></tbody></table>
<p>这是同一时刻的一次真实候选比较：两边只显示本轮改路车辆，并从完全相同的当前车位出发；其余车辆保留预约，整车队已通过完整碰撞检查。过去不变，当前装卸不中断。允许个别车稍晚完成，前提是固定任务的整体三元目标更好。此处预测只针对当前已接任务；后续新订单还会改变路线。</p>
<script>const data=__DATA__;const $=id=>document.getElementById(id);let t=0;
const colors=['#22679c','#a34b84','#ae721d','#267b69','#7859ab','#b74739','#32707a','#695630'];
const names={to_pickup:'去取货',to_delivery:'载货行驶',loading:'装货中',unloading:'卸货中',returning:'返回中',idle:'停车'};
const max=Math.max(...data.old.map(p=>p.length),...data.new.map(p=>p.length))-1;$('time').max=max;
$('summary').textContent=`中型仓库、6辆车、30单突发订单、种子0。重规划时刻 t=${data.event.time}。目标从 (${data.event.before.join(', ')}) 变为 (${data.event.after.join(', ')})：依次为剩余送达耗时之和、最晚回程结束时刻、剩余移动量。`;
for(const c of data.event.changes){const tr=document.createElement('tr');for(const x of [c.vehicle,names[c.state],c.old_delivery_end,c.new_delivery_end]){const td=document.createElement('td');td.textContent=x;tr.appendChild(td)}$('rows').appendChild(tr)}
function draw(id,paths){const c=$(id),ctx=c.getContext('2d'),s=data.scenario,size=Math.min(540/s.width,420/s.height),ox=15,oy=15;ctx.clearRect(0,0,570,460);const blocked=new Set(s.blocked.map(p=>p.join(',')));for(let y=0;y<s.height;y++)for(let x=0;x<s.width;x++){ctx.fillStyle=blocked.has([x,y].join(','))?'#536576':'#fff';ctx.fillRect(ox+x*size,oy+y*size,size,size);ctx.strokeStyle='#d8dfe5';ctx.strokeRect(ox+x*size,oy+y*size,size,size)}paths.forEach((p,k)=>{if(!p.length)return;ctx.strokeStyle=colors[k];ctx.lineWidth=2;ctx.beginPath();p.slice(0,t+1).forEach((q,i)=>{const x=ox+(q[0]+.5)*size,y=oy+(q[1]+.5)*size;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y)});ctx.stroke();const q=p[Math.min(t,p.length-1)];ctx.fillStyle=colors[k];ctx.beginPath();ctx.arc(ox+(q[0]+.5)*size,oy+(q[1]+.5)*size,size*.35,0,7);ctx.fill();ctx.fillStyle='white';ctx.textAlign='center';ctx.font='12px system-ui';ctx.fillText(k,ox+(q[0]+.5)*size,oy+(q[1]+.5)*size+4)})}
function render(){$('time').value=t;$('label').textContent=`时刻 ${data.event.time+t}（重规划后 ${t} 步）`;draw('before',data.old);draw('after',data.new)}
$('step').onclick=()=>{t=Math.min(max,t+1);render()};$('reset').onclick=()=>{t=0;render()};$('time').oninput=()=>{t=Number($('time').value);render()};render();</script></html>'''


def main():
    root=Path('algorithm_results')
    r=json.loads((root/'dynamic_medium_burst_0_joint_only.json').read_text())
    s=json.loads((root/'dynamic_medium_burst_0_input.json').read_text())
    event=max((e for e in r['replanning_events'] if e['time']>0 and e['after'][0]<e['before'][0] and len(e['changes'])>=3),key=lambda e:e['before'][0]-e['after'][0])
    t=event['time']
    old=[[] for _ in s['homes']];new=[[] for _ in s['homes']]
    for c in event['changes']:
        old[c['vehicle']]=c['old_suffix'];new[c['vehicle']]=c['new_suffix']
    data=dict(scenario=s,event=event,old=old,new=new)
    (root/'explanation_event.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    Path('途中联合重规划解释.html').write_text(PAGE.replace('__DATA__',json.dumps(data,ensure_ascii=False)),encoding='utf-8')
    print('Explanation event at',t,event['before'],'->',event['after'])


if __name__=='__main__':main()
