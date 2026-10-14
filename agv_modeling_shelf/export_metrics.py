"""导出每车、每单指标；汇总CSV由样例驱动生成。"""
import csv
from math import isclose
from pathlib import Path

SUMMARY_FIELDS = ('feasible','completed','total_tasks','completion_rate','comparison_valid','metrics_scope',
    'makespan','time','mean_flow_time','max_flow_time','p90_flow_time',
    'mean_dispatch_wait','mean_pickup_duration','mean_loaded_duration','mean_service_duration',
    'moves','empty_moves','loaded_moves','traffic_wait_steps','workload_cv')
VEHICLE_FIELDS = ('vehicle','assigned_tasks','completed_tasks','moves','empty_moves','loaded_moves',
    'task_busy_steps','task_utilization','service_steps','idle_steps','traffic_wait_steps')
TASK_FIELDS = ('task_id','vehicle','release','assigned_at','completed_at','flow_time',
    'dispatch_wait','pickup_duration','loaded_duration','service_duration')
TASK_FIELDS += ('shelf_x','shelf_y','pickup_x','pickup_y')


def export_details(result, directory, name):
    directory=Path(directory)
    for suffix, fields, rows in [('vehicles',VEHICLE_FIELDS,result['per_vehicle']),('tasks',TASK_FIELDS,result['task_metrics'])]:
        with (directory/(name+'_'+suffix+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader();writer.writerows(rows)


def audit_details(result, directory, name):
    for suffix,fields,expected in [('vehicles',VEHICLE_FIELDS,result['per_vehicle']),('tasks',TASK_FIELDS,result['task_metrics'])]:
        with (Path(directory)/(name+'_'+suffix+'.csv')).open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames != list(fields):raise ValueError('Detail CSV header mismatch')
            actual=list(reader)
        if len(actual)!=len(expected):raise ValueError('Detail CSV row count mismatch')
        for row,target in zip(actual,expected):
            for field in fields:
                if not (row[field]=='' if target[field] is None else isclose(float(row[field]),target[field])):
                    raise ValueError('Detail CSV value mismatch: '+field)
