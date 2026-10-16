#!/usr/bin/env python3
"""Build an offline, synchronized two-trace HTML replay (no server or CDN).

Both input pack_scene archives must contain independently valid executions of
exactly the same scenario. The page shows executed paths only; task markers and
rows appear only at their release time. Full-run scores remain offline labels.
"""

import argparse
import html
import json
import math
import re
from pathlib import Path

from agv.evaluation.validation import validate
from agv.io.scenes import scenario_id, unpack_scene


def _read(path):
    archive = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    scene = unpack_scene(archive)
    if "result" not in archive:
        raise ValueError("Replay inputs must contain an execution result")
    result = archive["result"]
    validate(scene, result)
    config = archive.get("config")
    config = config if isinstance(config, dict) else {}
    name = config.get("solver") or config.get("algorithm")
    if not isinstance(name, str):
        algorithm = result.get("algorithm")
        algorithm = algorithm if isinstance(algorithm, dict) else {}
        name = algorithm.get("assignment") or Path(path).stem
    return archive, scene, result, str(name)


def _metric(value, decimals=3):
    if type(value) not in (int, float) or not math.isfinite(value):
        return "不可比"
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else str(value)


def _panel(name, result, side):
    score = result.get("weighted_score") if result.get("score_valid") else None
    pairs = [
        ("F", _metric(score, 6)),
        ("T", _metric(result.get("makespan"))),
        ("R", _metric(result.get("mean_flow_time"))),
        ("D", _metric(result.get("moves"))),
        ("P90", _metric(result.get("p90_flow_time"))),
    ]
    metrics = " ".join(
        f"<span><b>{label}</b> {html.escape(value)}</span>" for label, value in pairs
    )
    status = "完整有效执行" if result["feasible"] else "未完成执行，成本不可作为完整任务对照"
    return (
        '<section class="panel">'
        f"<h2>{html.escape(name)}</h2><div class=metrics>{metrics}</div>"
        f"<p>{status}</p><canvas id=canvas-{side} aria-label='{html.escape(name, quote=True)} 仓库回放'></canvas>"
        f"<p id=status-{side} class=status aria-live=polite></p>"
        f"<div class=tasks><table><thead><tr><th>任务</th><th>层</th><th>状态</th>"
        f"<th>响应/已等</th></tr></thead><tbody id=tasks-{side}></tbody></table></div></section>"
    )


PAGE = r"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AGV 派单同步回放</title>
<style>
*{box-sizing:border-box}body{font:15px/1.5 system-ui,-apple-system,sans-serif;margin:0;background:#f3f5f7;color:#19252f}
main{max-width:1550px;margin:0 auto;padding:24px}h1{font-size:25px;margin:0 0 8px}h2{font-size:19px;margin:0 0 10px}
p{margin:8px 0;color:#52606d}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px;background:white;border:1px solid #ccd4db;border-radius:8px;margin:20px 0}
button,select{font:inherit;padding:6px 10px;background:white;border:1px solid #aebbc6;border-radius:5px}button{cursor:pointer}input[type=range]{flex:1;min-width:160px}output{font-variant-numeric:tabular-nums;min-width:125px}
.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.panel{background:white;border:1px solid #ccd4db;border-radius:8px;padding:16px;min-width:0}
.metrics{display:flex;gap:8px;flex-wrap:wrap;font-variant-numeric:tabular-nums}.metrics span{background:#eef3f7;padding:4px 8px;border-radius:4px}
canvas{display:block;width:100%;height:auto;background:#fff;border:1px solid #ced7dd}.status{min-height:44px}.tasks{max-height:240px;overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:5px 8px;border-bottom:1px solid #e3e7eb;font-variant-numeric:tabular-nums}.note{font-size:13px;overflow-wrap:anywhere}.legend{display:flex;gap:16px;flex-wrap:wrap}.key{display:inline-block;width:12px;height:12px;margin-right:4px;border:1px solid #73818b}.shelf{background:#d9bc77}.target{background:#ffe0d7;border-color:#c84430}.delivery{background:#d9f2df}.home{background:#dce9fb}
@media(max-width:850px){main{padding:12px}.columns{grid-template-columns:1fr}}
</style>
<main><h1>AGV 派单同步回放</h1>
<p>同一场景、同一离散时刻；顶部为完整运行的离线指标，回放包括最后卸货后的回库。</p>
<p class="note">场景 SHA256：__SHA__</p>
<div class=controls><button id=play type=button>播放</button><button id=reset type=button>回到起点</button>
<label for=speed>速度</label><select id=speed><option value=500>2 步/秒</option><option value=200 selected>5 步/秒</option><option value=100>10 步/秒</option><option value=40>25 步/秒</option></select>
<label for=clock>时间</label><input id=clock type=range min=0 max=__MAXTIME__ value=0 step=1><output id=timeLabel for=clock></output></div>
<div class=legend><span><i class="key shelf"></i>静态货架</span><span><i class="key target"></i>已发布且未取完目标</span><span><i class="key delivery"></i>D 卸货站</span><span><i class="key home"></i>专属停车位</span></div>
<div class=columns>__PANELS__</div>
<p class=note>只绘制已执行轨迹；不显示未来订单的目标与任务行。原地等待、装卸和返程均来自真实轨迹。滑块上限为两路执行结束时刻的较大值；较早结束的一路保持其最终位置。页面完全离线，不加载网络脚本或字体。</p>
</main><script id=replay-data type=application/json>__PAYLOAD__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('replay-data').textContent);
const slider=document.getElementById('clock'), play=document.getElementById('play'), speed=document.getElementById('speed');
const palette=['#2367b3','#d04b35','#27854d','#8756ad','#d18217','#168b99','#a94777','#6f6f26','#315b7c','#845238'];
const cell=23,pad=15,scene=data.scene,maxTime=data.maxTime;
const releasedAt=(time)=>scene.tasks.filter(job=>job.release<=time);
function textCell(row,value){const td=document.createElement('td');td.textContent=String(value);row.appendChild(td);}
function draw(side,time){
 const run=data[side], canvas=document.getElementById('canvas-'+side),ctx=canvas.getContext('2d');
 if(canvas.width!==scene.width*cell+2*pad){canvas.width=scene.width*cell+2*pad;canvas.height=scene.height*cell+2*pad;}
 const point=(p)=>[pad+p[0]*cell,pad+p[1]*cell];
 const fill=(p,color)=>{const [x,y]=point(p);ctx.fillStyle=color;ctx.fillRect(x+1,y+1,cell-2,cell-2);};
 const label=(p,value,color='#243443')=>{const [x,y]=point(p);ctx.fillStyle=color;ctx.font='12px system-ui';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(value,x+cell/2,y+cell/2);};
 ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
 ctx.strokeStyle='#edf0f2';ctx.lineWidth=1;
 for(let x=0;x<=scene.width;x++){ctx.beginPath();ctx.moveTo(pad+x*cell,pad);ctx.lineTo(pad+x*cell,pad+scene.height*cell);ctx.stroke();}
 for(let y=0;y<=scene.height;y++){ctx.beginPath();ctx.moveTo(pad,pad+y*cell);ctx.lineTo(pad+scene.width*cell,pad+y*cell);ctx.stroke();}
 for(const p of scene.blocked)fill(p,'#a8b0b7');
 for(const p of scene.shelves)fill(p,'#d9bc77');
 scene.homes.forEach((p,i)=>{fill(p,'#dce9fb');label(p,'H'+i);});
 for(const p of (scene.stations||[])){fill(p,'#d9f2df');label(p,'D');}
 const events=new Map(run.events.map(event=>[event.task_id,event]));
 const released=releasedAt(time);
 for(const job of released){const event=events.get(job.id);if(event&&event.pickup_end<=time)continue;const p=job.shelf||job.pickup;if(!p)continue;fill(p,'#ffe0d7');const [x,y]=point(p);ctx.strokeStyle='#c84430';ctx.lineWidth=2;ctx.strokeRect(x+2,y+2,cell-4,cell-4);}
 run.paths.forEach((path,k)=>{
  const last=Math.min(time,path.length-1),color=palette[k%palette.length];ctx.strokeStyle=color+'55';ctx.lineWidth=2;ctx.beginPath();
  for(let i=0;i<=last;i++){const [x,y]=point(path[i]);if(i===0)ctx.moveTo(x+cell/2,y+cell/2);else ctx.lineTo(x+cell/2,y+cell/2);}ctx.stroke();
  const [x,y]=point(path[last]);ctx.fillStyle=color;ctx.beginPath();ctx.arc(x+cell/2,y+cell/2,cell*.36,0,Math.PI*2);ctx.fill();label(path[last],String(k),'#fff');
 });
 const completed=released.filter(job=>{const e=events.get(job.id);return e&&e.delivery_end<=time;}).length;
 const picked=released.filter(job=>{const e=events.get(job.id);return e&&e.pickup_end<=time;}).length;
 document.getElementById('status-'+side).textContent=`已发布 ${released.length} 单；已取完 ${picked} 单；已交付 ${completed} 单。执行结束 t=${run.time}${time>=run.time?'（已停在最终位置）':''}`;
 const body=document.getElementById('tasks-'+side);body.replaceChildren();
 const unfinished=released.filter(job=>{const e=events.get(job.id);return !e||e.delivery_end>time;});
 for(const job of unfinished){
  const e=events.get(job.id);let state='待派单';
  if(e&&e.assigned_at<=time){state=time<e.pickup_arrival?'空载赴货架':time<e.pickup_end?'装货':time<e.delivery_arrival?'载货运输':'卸货';}
  const row=document.createElement('tr');textCell(row,job.id);textCell(row,job.shelf_level||1);textCell(row,state);textCell(row,time-job.release);body.appendChild(row);
 }
 if(!unfinished.length){const row=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent=released.length?'当前已发布订单均已交付':'尚无已发布订单';row.appendChild(td);body.appendChild(row);}
}
function render(){const time=Number(slider.value);document.getElementById('timeLabel').textContent=`t = ${time} / ${maxTime}`;draw('left',time);draw('right',time);}
let timer=null;
function stop(){if(timer!==null)clearInterval(timer);timer=null;play.textContent='播放';}
function start(){stop();if(Number(slider.value)>=maxTime)slider.value=0;play.textContent='暂停';timer=setInterval(()=>{slider.value=Math.min(maxTime,Number(slider.value)+1);render();if(Number(slider.value)>=maxTime)stop();},Number(speed.value));}
play.addEventListener('click',()=>timer===null?start():stop());
document.getElementById('reset').addEventListener('click',()=>{stop();slider.value=0;render();});
slider.addEventListener('input',()=>{stop();render();});speed.addEventListener('change',()=>{if(timer!==null)start();});
render();
</script></html>"""


def build_replay(left, right, output):
    a, scene, a_result, a_name = _read(left)
    b, other, b_result, b_name = _read(right)
    digest = a.get("scenario_sha256")
    if not isinstance(digest, str) or digest != b.get("scenario_sha256"):
        raise ValueError("Replay archives must preserve an identical scenario_sha256")
    if scenario_id(scene) != scenario_id(other):
        raise ValueError("Replay inputs describe different scenarios")
    maximum = max(a_result["time"], b_result["time"])

    def view(result):
        return {key: result[key] for key in ("time", "paths", "events")}

    payload = json.dumps(
        dict(scene=scene.to_dict(), maxTime=maximum, left=view(a_result), right=view(b_result)),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    for raw, escaped in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        payload = payload.replace(raw, escaped)
    substitutions = dict(
        SHA=html.escape(digest),
        MAXTIME=str(maximum),
        PANELS=_panel(a_name, a_result, "left") + _panel(b_name, b_result, "right"),
        PAYLOAD=payload,
    )
    # One pass: user text resembling a template marker must remain literal.
    page = re.sub(
        r"__(SHA|MAXTIME|PANELS|PAYLOAD)__",
        lambda match: substitutions[match.group(1)],
        PAGE,
    )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as file:
        file.write(page)
    return dict(output=str(target), scenario_sha256=digest, synchronized_end=maximum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(build_replay(args.left, args.right, args.output), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
