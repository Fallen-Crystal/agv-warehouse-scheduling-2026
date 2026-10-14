"""展示实际时空A*的局部避让；不是完整订单实验或训练结果。"""
import json
from pathlib import Path
from model import Scenario
from routing import Router


def cases():
    entries=[]
    for name, bay, entry in [('侧边让行',True,False),('入口等待',False,True),('没有错车位置',False,False)]:
        free={(x,2) for x in range(7)}|{(0,0),(6,0)}
        if bay:free.add((4,1))
        if entry:free.update({(5,1),(5,3)})
        s=Scenario(7,4,{(x,y) for x in range(7) for y in range(4)}-free,
                   set(),[(0,0),(6,0)],[],30).check()
        router=Router(s)
        leader=router.leg((1,2),(5,3) if entry else (6,2),0,0,set(),set())
        vertices={(t,p) for t,p in enumerate(leader)}
        vertices.update((t,leader[-1]) for t in range(len(leader),s.horizon+1))
        edges={(t,a,b) for t,(a,b) in enumerate(zip(leader,leader[1:]))}
        follower=router.leg((5,1) if entry else (5,2),(0,2),0,1,vertices,edges)
        entries.append(dict(name=name,width=7,height=4,blocked=sorted(s.blocked),
                            leader=leader,follower=follower,start=[5,1] if entry else [5,2],
                            note=('绿色车退到侧边空位，等蓝色车通过后继续前进。' if bay else
                                  '绿色车在入口等待，等蓝色车离开通道后进入。' if entry else
                                  '按蓝色车已有路线，绿色车找不到安全路线；不能把等待当成必然能解决堵塞。')))
    return entries


PAGE=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>车辆迎面避让演示</title><style>
body{font-family:"Microsoft YaHei",sans-serif;background:#edf2f6;color:#243449;margin:30px auto;max-width:850px;padding:20px}
canvas{background:white;max-width:100%;border:1px solid #bbcbd8}button,select{font:inherit;padding:10px;margin-right:10px}p{line-height:1.8}
</style><h1>车辆迎面避让演示</h1>
<p>蓝色车先排路线，绿色车根据它的路线避让。这里直接使用现有路径规划器计算局部行驶路线，不包含取货订单，也不是强化学习训练。</p>
<select id="case"></select><button id="play">播放</button><button id="next">下一步</button><button id="reset">回到开始</button>
<p id="note"></p><canvas id="map" width="700" height="400"></canvas>
<p>时刻：<span id="time"></span>　<input id="slider" type="range" min="0" value="0"></p><p id="status"></p>
<p>白色格可通行，深色格为障碍。正式订单仿真会在接单时考虑其他车已排的路线；已安排的避让动作随后逐步执行。不会临时移动其他正在执行任务车辆的已排路线。</p>
<script>
const cases=__DATA__, $=id=>document.getElementById(id),ctx=$('map').getContext('2d');let n=0,t=0,timer=null;
cases.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=c.name;$('case').appendChild(o)});
function stop(){clearInterval(timer);timer=null;$('play').textContent='播放'}
function draw(){const c=cases[n],end=c.follower?Math.max(c.leader.length,c.follower.length)-1:0;
ctx.clearRect(0,0,700,400);for(let y=0;y<4;y++)for(let x=0;x<7;x++){ctx.fillStyle=c.blocked.some(p=>p[0]===x&&p[1]===y)?'#536576':'#fff';ctx.fillRect(x*100,y*100,100,100);ctx.strokeStyle='#cbd5df';ctx.strokeRect(x*100,y*100,100,100)}
[c.leader,c.follower||[c.start]].forEach((path,k)=>{const p=path[Math.min(t,path.length-1)];ctx.fillStyle=k?'#16816c':'#176ca7';ctx.beginPath();ctx.arc(p[0]*100+50,p[1]*100+50,27,0,Math.PI*2);ctx.fill();ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.textAlign='center';ctx.fillText(k?'让行车':'先行车',p[0]*100+50,p[1]*100+57)});
$('time').textContent=t+' / '+end;$('slider').max=end;$('slider').value=t;$('note').textContent=c.note;
if(!c.follower)$('status').textContent='未找到安全路线：绿色车不执行移动。演示保持两车在原位，等待重新协调路线。';
else{const p=c.follower[Math.min(t,c.follower.length-1)],prev=c.follower[Math.max(0,Math.min(t-1,c.follower.length-1))];$('status').textContent=t>=c.follower.length-1?'让行车已通过。':p[1]!==2?'让行车在侧边空位或入口。':t>0&&p[0]===prev[0]&&p[1]===prev[1]?'让行车正在等待。':'让行车正在行驶。'}
}
$('case').onchange=()=>{stop();n=Number($('case').value);t=0;draw()};$('reset').onclick=()=>{stop();t=0;draw()};
$('next').onclick=()=>{stop();t=Math.min(t+1,Number($('slider').max));draw()};$('slider').oninput=()=>{stop();t=Number($('slider').value);draw()};
$('play').onclick=()=>{if(timer){stop();return}if(t>=Number($('slider').max))t=0;$('play').textContent='暂停';timer=setInterval(()=>{if(t>=Number($('slider').max)){stop();return}t++;draw()},650)};draw();
</script></html>'''


def build():
    folder=Path(__file__).parent
    entries=cases()
    (folder/'车辆迎面避让演示.html').write_text(PAGE.replace('__DATA__',json.dumps(entries,ensure_ascii=False)),encoding='utf-8')
    (folder/'examples'/'避让演示路线.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':build()
