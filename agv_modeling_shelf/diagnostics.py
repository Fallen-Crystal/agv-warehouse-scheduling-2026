"""执行记录：区分规划请求失败、任务未完成和最终返程。"""
def summarize_failures(scenario, result, attempts, execution_error=None):
    assigned={r['task_id']:r for r in result['assignments']}
    completed={r['task_id'] for r in result['events']}
    time=result['time']
    unfinished=[]
    for j in scenario.tasks:
        if j.id in completed:continue
        state='not_released' if j.release>time else 'executing' if j.id in assigned else 'waiting_assignment'
        failures=[a for a in attempts if a['task_id']==j.id]
        unfinished.append(dict(task_id=j.id,status=state,release=j.release,
            elapsed_since_release=max(0,time-j.release),planning_failures=len(failures),
            last_failed_leg=failures[-1]['failed_leg'] if failures else None))
    legs={name:sum(a['failed_leg']==name for a in attempts) for name in ('pickup','delivery','return')}
    return dict(planning_failure_count=len(attempts),planning_failure_by_leg=legs,
        planning_failures=attempts,unfinished_tasks=unfinished,
        vehicles_away_from_home=[k for k,(path,home) in enumerate(zip(result['paths'],scenario.homes)) if tuple(path[-1])!=home],
        execution_error=execution_error,
        note='规划失败指当前预约和时限下该次尝试失败，不证明问题无解；等待派单不自动等于死锁。')
