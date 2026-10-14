"""保存完整场景，读取后使用场景本身重新运行，不用种子重建。"""
import json
import hashlib
from pathlib import Path
from model import Scenario


def scenario_id(scenario):
    raw=json.dumps(scenario.to_dict(),sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def pack_scene(scenario, config=None, result=None):
    data=dict(format='agv-scene-v2',scenario=scenario.to_dict(),scenario_sha256=scenario_id(scenario),config=config)
    if result is not None:data['result']=result
    return data


def unpack_scene(data):
    if not isinstance(data,dict):raise ValueError('场景文件必须是JSON对象')
    if 'format' in data and data['format'] not in ('agv-scene-v1','agv-scene-v2'):raise ValueError('不支持的场景格式')
    raw=data.get('scenario',data)
    s=Scenario.from_dict(raw)
    raw_id=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if data.get('scenario_sha256') and data['scenario_sha256'] not in (scenario_id(s),raw_id):
        raise ValueError('场景校验值不一致；文件内容可能被修改')
    return s


def save_scene(path,scenario,config=None,result=None):
    Path(path).write_text(json.dumps(pack_scene(scenario,config,result),ensure_ascii=False,indent=2),encoding='utf-8')


def load_scene(path):
    return unpack_scene(json.loads(Path(path).read_text(encoding='utf-8-sig')))
