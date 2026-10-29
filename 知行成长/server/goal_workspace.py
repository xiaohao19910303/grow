"""Additive goal workspace; action facts and their P0 contract remain authoritative."""
from zoneinfo import ZoneInfo
from fastapi import Request
from pydantic import Field
import action_plans as a

VERSION = 1


def require_workspace(request):
    if request.headers.get('X-Grow-Workspace-Version') != str(VERSION):
        a.fail(409, '目标工作区已升级，请刷新页面后重试，输入已保留。', 'CONTRACT_UPGRADE_REQUIRED')


def guard_fields(request, fields):
    with a.connection() as c:
        extended = a.workspace_extended(fields.model_dump(mode='json'),c)
    if extended: require_workspace(request)


def guard_mutation(request, pid, body):
    with a.connection() as c:
        plan = a.get(c, pid)
    if plan.get('workspace_version') or plan['period'] == 'custom':
        require_workspace(request)
    if body.fields:
        guard_fields(request, body.fields)
    if body.action=='reschedule' and plan.get('parent_id') and 'date' in body.model_fields_set:
        values={k:v for k,v in plan.items() if k in a.PlanFields.model_fields}
        values.update(start_date=body.date,end_date=body.date)
        if body.date is None: values.update(at=None,reminder=False)
        guard_fields(request,a.PlanFields.model_validate(values))


def result(plan):
    metric = plan.get('result_metric') or {'mode': 'unset'}
    mode = metric['mode']; target = metric.get('target'); current = metric.get('current', 0)
    if mode == 'actions': current = plan['progress']['completed']
    if mode == 'milestones':
        milestones = metric.get('milestones', [])
        target = len(milestones); current = sum(m['completed'] for m in milestones)
    percent = min(100, round(current / target * 100, 1)) if mode != 'unset' and target else None
    return dict(mode=mode, current=current, target=target, unit=metric.get('unit', ''), percent=percent,
                ready=bool(target and current >= target))


def project(snapshot):
    plans = snapshot['plans']; by_id = {p['id']: p for p in plans}
    for plan in plans:
        plan['result'] = result(plan) if plan['entity_type'] == 'goal' else None
        plan['goal_id'] = plan['id'] if plan['entity_type'] == 'goal' else None
        plan['outside_period'] = False
        cursor = plan; visited = set()
        while cursor.get('parent_id') and cursor['parent_id'] not in visited:
            visited.add(cursor['parent_id']); parent = by_id.get(cursor['parent_id'])
            if not parent: break
            if parent['entity_type'] == 'goal': plan['goal_id'] = parent['id']
            if parent.get('start_date') and plan.get('start_date'):
                plan['outside_period'] |= plan['start_date'] < parent['start_date'] or plan['end_date'] > parent['end_date']
            cursor = parent
        plan['deadline_passed'] = bool(plan.get('deadline') and plan['deadline'] < a.clock().astimezone(ZoneInfo(plan['timezone'])).date().isoformat() and plan['status']=='active')
    return {**snapshot, 'workspace_version': VERSION}


class ResultUpdate(a.Input):
    key: str = Field(min_length=8, max_length=160)
    revision: int = Field(ge=1, strict=True)
    metric: a.ResultMetric
    note: str = Field(default='', max_length=1000)


def update_result(pid, body):
    with a.connection(True) as c:
        def work():
            plan = a.get(c, pid)
            if plan['entity_type'] != 'goal': a.fail(422, '请选择目标。')
            if plan['revision'] != body.revision: a.fail(409, '目标已变化，请核对后保存。', 'REVISION_CONFLICT')
            if plan['status'] != 'active': a.fail(409, '请先恢复目标。')
            plan['result_history'] = [*plan.get('result_history', []), dict(at=a.clock().isoformat(), metric=plan.get('result_metric'), revision=plan['revision'], note=body.note)]
            plan.update(result_metric=body.metric.model_dump(mode='json'), revision=plan['revision']+1, workspace_version=VERSION, updated_at=a.clock().isoformat())
            a.write(c, plan)
            return {'plan': plan}
        return a.operation(c, body.key, {'op': 'goal-result', 'id': pid, **body.model_dump(mode='json')}, work)


def register(router):
    @router.get('/workspace')
    def workspace(): return project(a.listing())

    @router.get('/goals')
    def goals(): return {'goals': [p for p in project(a.listing())['plans'] if p['entity_type']=='goal']}

    @router.post('/goals')
    def create_goal(body: a.NewPlan, request: Request):
        require_workspace(request)
        if body.entity_type != 'goal': a.fail(422, '请选择目标类型。')
        return a.create(body)

    @router.get('/goals/{pid}')
    def goal(pid: str):
        plan = next((p for p in project(a.listing())['plans'] if p['id']==pid and p['entity_type']=='goal'), None)
        if not plan: a.fail(404, '目标不存在。')
        return {'plan': plan}

    @router.post('/goals/{pid}/operations')
    def operate_goal(pid: str, body: a.Mutation, request: Request):
        require_workspace(request)
        with a.connection() as c:
            if a.get(c,pid)['entity_type']!='goal': a.fail(422,'请选择目标。')
        return a.mutate(pid,body)

    @router.post('/goals/{pid}/result')
    def save_result(pid: str, body: ResultUpdate, request: Request):
        require_workspace(request)
        return update_result(pid, body)

    from goal_planning import register as register_planning
    register_planning(router)
