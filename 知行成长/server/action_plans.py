"""Private action plans and explicit execution facts; independent of course completion."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from datetime import date as CalendarDate
import hashlib
import json
import re
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = '''
CREATE TABLE IF NOT EXISTS action_plans (id TEXT PRIMARY KEY,data TEXT NOT NULL,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS action_executions (
 id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES action_plans(id),state TEXT NOT NULL,data TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS action_one_running ON action_executions(state) WHERE state='running';
CREATE INDEX IF NOT EXISTS action_execution_plan ON action_executions(plan_id);
CREATE TABLE IF NOT EXISTS action_operations (key TEXT PRIMARY KEY,hash TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_link_state (id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL,backup TEXT);
CREATE TABLE IF NOT EXISTS action_reviews (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_reports (id TEXT PRIMARY KEY,state TEXT NOT NULL,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_content_events (id TEXT PRIMARY KEY,request_key TEXT UNIQUE,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_reminder_claims (key TEXT PRIMARY KEY,claimed_at TEXT NOT NULL);
'''


def clock():
    return datetime.now(timezone.utc)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class ActionError(HTTPException):
    def __init__(self, status, message, code=None, **extra):
        super().__init__(status, message)
        self.code = code or {422:'VALIDATION_ERROR',409:'STATE_CONFLICT',404:'NOT_FOUND'}.get(status,'REQUEST_REJECTED')
        self.extra = extra


def fail(status, message, code=None, **extra):
    raise ActionError(status, message, code, **extra)


@contextmanager
def connection(write=False, allow_link=False):
    with db.connect() as c:
        tables=c.execute("SELECT to_regclass('action_link_state') AS link,to_regclass('action_reviews') AS reviews").fetchone()
        if tables[0] is None or tables[1] is None or c.execute("SELECT to_regclass('action_content_events')").fetchone()[0] is None:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':actions-schema',0))")
            c.executescript(SCHEMA)
        if write:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':actions-write',0))")
            if not allow_link:
                row = c.execute('SELECT data FROM action_link_state WHERE id=1').fetchone()
                if row and json.loads(row[0]).get('phase') in ('pending','active'):
                    fail(409, '计划已开始由 LightTick 接管，请刷新后继续；本地输入已保留。')
        yield c


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StudyTarget(Input):
    kind: Literal['library', 'book', 'renzhi', 'yingyu', 'biaoda', 'plan', 'article'] = 'library'
    course: str = Field(default='', max_length=500)
    plan_id: str = Field(default='', max_length=80)
    lesson_no: int = Field(default=1, ge=1, le=100000)

    @model_validator(mode='after')
    def safe_reference(self):
        if self.kind in ('yingyu', 'biaoda') and (not self.course or any(p in ('', '.', '..') for p in self.course.split('/')) or '\\' in self.course):
            raise ValueError('请选择有效的课程。')
        if self.kind == 'article' and not re.fullmatch(r'article-[a-zA-Z0-9-]{1,100}', self.course):
            raise ValueError('请选择有效的历史文章。')
        if self.kind == 'plan' and not re.fullmatch(r'plan-[a-zA-Z0-9-]{1,70}', self.plan_id):
            raise ValueError('请选择有效的学习计划课程。')
        if any(ord(ch) < 32 for ch in self.course):
            raise ValueError('课程标识无效。')
        return self


class PlanFields(Input):
    title: str = Field(min_length=1, max_length=160)
    period: Literal['year', 'month', 'week', 'day']
    horizon: Literal['short', 'long'] | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = Field(default='Asia/Shanghai', max_length=80)
    parent_id: str | None = Field(default=None, max_length=80)
    target_minutes: int | None = Field(default=20, ge=1, le=1440, strict=True)
    target_count: int = Field(default=1, ge=1, le=1000, strict=True)
    minimum_minutes: int | None = Field(default=5, ge=1, le=1440, strict=True)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440, strict=True)
    at: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    reminder: bool = False
    reason: str = Field(default='', max_length=1000)
    if_then: str = Field(default='', max_length=1000)
    target: StudyTarget | None = None
    completion_mode: Literal['time', 'content', 'check'] = 'time'

    @model_validator(mode='after')
    def valid_period(self):
        self.title = self.title.strip()
        self.horizon = self.horizon or ('long' if self.period == 'year' else 'short')
        if not self.title or (self.start_date is None) != (self.end_date is None):
            raise ValueError('标题和计划日期范围无效。')
        if self.start_date is None:
            if self.period != 'day' or self.at is not None or self.parent_id:
                raise ValueError('未安排行动不能设置时间或上级。')
        elif self.end_date < self.start_date or (self.end_date-self.start_date).days > 366:
            raise ValueError('计划日期范围无效。')
        if self.period == 'day' and (self.target_count != 1 or self.start_date != self.end_date):
            raise ValueError('日行动对应同一天和一次完成。')
        if self.completion_mode != 'time' and self.period != 'day':
            raise ValueError('只有日行动可以按内容或勾选完成。')
        if self.completion_mode == 'content':
            if not self.target or self.target.kind not in ('article','plan'):
                raise ValueError('请选择已支持完成确认的文章或课程计划课程；其他课程可按时长安排。')
        if self.completion_mode != 'time':
            self.target_minutes = self.minimum_minutes = None
            if self.completion_mode == 'check': self.target = None
        else:
            if self.target_minutes is None: raise ValueError('请填写标准分钟。')
            if 'minimum_minutes' not in self.model_fields_set:
                self.minimum_minutes = min(5,self.target_minutes)
            if self.minimum_minutes is not None and self.minimum_minutes > self.target_minutes:
                raise ValueError('起步时长不能超过标准时长。')
            self.estimated_minutes = None
        if self.reminder and (not self.start_date or not self.at):
            raise ValueError('提醒需要日期和具体时间。')
        if self.period == 'week' and (self.end_date-self.start_date).days > 6:
            raise ValueError('周计划最多包含七天。')
        if self.period == 'month' and (self.start_date.year,self.start_date.month) != (self.end_date.year,self.end_date.month):
            raise ValueError('月计划的日期需在同一个月。')
        if self.period == 'year' and self.start_date.year != self.end_date.year:
            raise ValueError('年目标的日期需在同一年。')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('时区无效。') from None
        return self


class NewPlan(PlanFields):
    key: str = Field(min_length=8, max_length=160)
    repeat_dates: list[date] = Field(default_factory=list, max_length=7)


class Mutation(Input):
    key: str = Field(min_length=8, max_length=160)
    revision: int = Field(ge=1, strict=True)
    action: Literal['edit', 'pause', 'resume', 'archive', 'complete', 'start', 'finish', 'snooze', 'reschedule', 'cancel', 'reopen', 'reconcile', 'reconcile-content', 'complete-time']
    date: CalendarDate | None = None
    source_event_id: str | None = Field(default=None,max_length=80)
    fields: PlanFields | None = None
    variant: Literal['standard', 'minimum'] = 'standard'
    execution_id: str | None = Field(default=None, max_length=80)
    outcome: Literal['completed', 'interrupted'] = 'completed'
    actual_minutes: int = Field(default=0, ge=0, le=1440, strict=True)
    note: str = Field(default='', max_length=2000)
    snooze_minutes: int = Field(default=15, ge=5, le=120, strict=True)


def public(row):
    data = json.loads(row['data'])
    data.setdefault('schema_version',1)
    data.setdefault('completed_at',None); data.setdefault('completion_record_id',None)
    data.setdefault('estimated_minutes',data.get('target_minutes') if data.get('completion_mode') in ('content','check') else None)
    return {**data, 'completion_mode': data.get('completion_mode', 'time'), 'horizon': data.get('horizon') or ('long' if data['period'] == 'year' else 'short'), 'id': row['id'], 'revision': row['revision']}


def target_identity(target):
    if not target: return None
    kind=target['kind']
    keys={'article':('course',),'plan':('plan_id','lesson_no'),'renzhi':('lesson_no',),'yingyu':('course',),'biaoda':('course',)}
    return (kind,*(target.get(k,1 if k=='lesson_no' else '') for k in keys.get(kind,())))


def same_target(left,right):
    return target_identity(left)==target_identity(right)


def duplicate_schedule(c, fields, exclude=None):
    if fields.get('completion_mode') != 'content':
        return None
    for row in c.execute('SELECT * FROM action_plans'):
        other = public(row)
        if (other['id'] != exclude and other['period'] == 'day' and other['status'] != 'archived'
                and other['completion_mode'] == 'content' and other['start_date'] == fields['start_date']
                and other['timezone'] == fields['timezone'] and same_target(other['target'], fields['target'])):
            return other
    return None


def get(c, pid):
    row = c.execute('SELECT * FROM action_plans WHERE id=?', (pid,)).fetchone()
    if not row:
        fail(404, '行动计划不存在。')
    return public(row)


def write(c, plan):
    c.execute('UPDATE action_plans SET data=?,revision=? WHERE id=?', (encoded(plan), plan['revision'], plan['id']))


def operation(c, key, payload, work):
    fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
    old = c.execute('SELECT * FROM action_operations WHERE key=?', (key,)).fetchone()
    if old:
        if old['hash'] != fingerprint:
            fail(409, '这个请求编号已用于其他内容，请刷新后核对。')
        return json.loads(old['result'])
    result = work()
    c.execute('INSERT INTO action_operations VALUES (?,?,?)', (key, fingerprint, encoded(result)))
    return result


def due_at(fields):
    if not fields.get('start_date') or not fields.get('at'): return None
    local = datetime.combine(date.fromisoformat(str(fields['start_date'])), time.fromisoformat(fields['at']), ZoneInfo(fields['timezone']))
    # Reject local times skipped by a daylight-saving transition.
    utc = local.astimezone(timezone.utc)
    if utc.astimezone(local.tzinfo).replace(tzinfo=None) != local.replace(tzinfo=None):
        fail(422, '这个时间处于夏令时跳变中，请选择其他时间。')
    return utc.isoformat()


def validate_parent(c, fields, existing=None):
    parent_id = fields['parent_id']
    if parent_id:
        parent = get(c, parent_id)
        levels = {'year': 0, 'month': 1, 'week': 2, 'day': 3}
        if levels[parent['period']] >= levels[fields['period']] or parent['status'] == 'archived':
            fail(422, '请选择有效的上级年、月或周计划。')
        if not fields['start_date'] or not parent['start_date'] <= fields['start_date'] <= fields['end_date'] <= parent['end_date'] or fields['timezone'] != parent['timezone']:
            fail(422, '子计划的日期和时区需在上级计划范围内。')
    target = fields['target']
    if target and target['kind'] in ('plan', 'article'):
        table = 'learning_lessons' if target['kind'] == 'plan' else 'reading_records'
        if c.execute('SELECT to_regclass(?)', (table,)).fetchone()[0] is None:
            fail(404, '关联的学习内容不存在。')
        found = c.execute('SELECT 1 FROM learning_lessons WHERE plan_id=? AND lesson_no=?', (target['plan_id'], target['lesson_no'])).fetchone() if table == 'learning_lessons' else c.execute('SELECT 1 FROM reading_records WHERE id=?', (target['course'],)).fetchone()
        if not found:
            fail(404, '关联的学习内容不存在。')
    if existing:
        if fields['period'] != existing['period']:
            fail(422, '计划周期不能直接改变，请新建另一周期的计划。')
        children = [public(r) for r in c.execute('SELECT * FROM action_plans') if json.loads(r['data']).get('parent_id') == existing['id']]
        if any(not fields['start_date'] <= child['start_date'] <= child['end_date'] <= fields['end_date'] or child['timezone'] != fields['timezone'] for child in children):
            fail(422, '调整日期前请先处理已有子计划。')
    duplicate=duplicate_schedule(c,fields,existing['id'] if existing else None)
    if duplicate:
        fail(409,'这份内容在该日期已有安排，请查看或调整已有安排。','DUPLICATE_SCHEDULE',existing_plan_id=duplicate['id'])


def create(body):
    with connection(True) as c:
        def work():
            if c.execute('SELECT count(*) FROM action_plans').fetchone()[0] + max(1, len(body.repeat_dates)) > 1000:
                fail(422, '计划数量已达首版上限，请先整理历史计划。')
            dates = body.repeat_dates or [body.start_date]
            if body.repeat_dates and (body.period != 'day' or len(set(dates)) != len(dates) or (max(dates) - min(dates)).days > 6 or body.start_date not in dates):
                fail(422, '重复日行动请选择同一七天内不重复的日期，并包含首日。')
            result = []
            for day in sorted(dates,key=lambda d:str(d or '')):
                fields = body.model_dump(mode='json', exclude={'key', 'repeat_dates'})
                if body.repeat_dates:
                    fields.update(start_date=day.isoformat(), end_date=day.isoformat())
                validate_parent(c, fields)
                pid = 'action-' + uuid.uuid4().hex
                plan = {**fields, 'id': pid, 'schema_version':2,'completed_at':None,'completion_record_id':None,'revision': 1, 'status': 'active', 'created_at': clock().isoformat(),
                        'reminder_at': due_at(fields), 'updated_at': clock().isoformat()}
                c.execute('INSERT INTO action_plans VALUES (?,?,1)', (pid, encoded(plan)))
                result.append(plan)
            return {'plans': result}
        return operation(c, body.key, body.model_dump(mode='json'), work)


def active(c):
    row = c.execute("SELECT data FROM action_executions WHERE state='running'").fetchone()
    return json.loads(row[0]) if row else None


class Schedule(Input):
    title: str = Field(min_length=1, max_length=160)
    target: StudyTarget
    date: CalendarDate | None = None
    timezone: str = 'Asia/Shanghai'
    target_minutes: int | None = Field(default=None, ge=1, le=1440, strict=True)
    estimated_minutes: int | None = Field(default=None,ge=1,le=1440,strict=True)
    key: str = Field(min_length=8, max_length=160)


def schedule(body):
    if body.target_minutes is not None and body.estimated_minutes is not None and body.target_minutes!=body.estimated_minutes:fail(422,'预计分钟字段不一致。')
    fields = NewPlan(title=body.title, period='day', start_date=body.date, end_date=body.date,
                     timezone=body.timezone, target=body.target, target_minutes=body.target_minutes,
                     minimum_minutes=None, estimated_minutes=body.estimated_minutes if body.estimated_minutes is not None else body.target_minutes, completion_mode='content', key=body.key)
    with connection(True) as c:
        def work():
            old = duplicate_schedule(c, fields.model_dump(mode='json'))
            if old:
                return {'plan': old, 'existing': True}
            # The tenant write lock is reentrant in this transaction; create in
            # this connection so different request keys cannot race duplicates.
            data = fields.model_dump(mode='json', exclude={'key', 'repeat_dates'})
            validate_parent(c, data)
            if c.execute('SELECT count(*) FROM action_plans').fetchone()[0] >= 1000:
                fail(422, '安排数量已达上限，请先整理历史安排。')
            pid = 'action-' + uuid.uuid4().hex
            plan = {**data, 'id': pid, 'schema_version':2,'completed_at':None,'completion_record_id':None,'revision': 1, 'status': 'active', 'created_at': clock().isoformat(),
                    'updated_at': clock().isoformat(), 'reminder_at': due_at(data)}
            c.execute('INSERT INTO action_plans VALUES (?,?,1)', (pid, encoded(plan)))
            return {'plan': plan, 'existing': False}
        return operation(c, body.key, {'op': 'schedule', **body.model_dump(mode='json')}, work)


def fact_public(data):
    data=dict(data)
    if 'record_kind' not in data:
        data['record_kind']='completion' if data.get('completion_mode') in ('content','check') and not data.get('actual_minutes') else 'session'
        data['schema_version']=1
        data['date_basis']='legacy_planned'
    data.setdefault('completion_effect','complete' if data.get('outcome')=='completed' else 'none')
    return data


def facts(c,pid=None):
    rows=c.execute('SELECT data FROM action_executions'+(' WHERE plan_id=?' if pid else ''),[pid] if pid else []).fetchall()
    return [fact_public(json.loads(r[0])) for r in rows]


def progress_for(records,ids):
    selected=[r for r in records if r['plan_id'] in ids and r['outcome']!='running']
    reversed_ids={r.get('reverses_record_id') for r in selected if r.get('completion_effect')=='reopen'}
    done={r['plan_id'] for r in selected if r.get('completion_effect')=='complete' and r['id'] not in reversed_ids}
    return dict(minutes=sum(r['actual_minutes'] for r in selected if r['record_kind']=='session'),completed=len(done),
                minimum=sum(r['outcome']=='minimum' for r in selected),partial=sum(r['outcome']=='partial' for r in selected),
                interrupted=sum(r['outcome']=='interrupted' for r in selected))


def executable(c,plan):
    if not plan.get('start_date'):fail(422,'请先安排日期。','UNSCHEDULED_ACTION')
    today=clock().astimezone(ZoneInfo(plan['timezone'])).date().isoformat()
    if plan['start_date']>today:fail(422,'未来行动请先改期再执行。','FUTURE_ACTION')
    ancestor=plan
    while ancestor.get('parent_id'):
        ancestor=get(c,ancestor['parent_id'])
        if ancestor['status']!='active':fail(409,'请先恢复上级计划。')


def make_fact(plan,kind='session',stamp=None):
    stamp=stamp or clock().isoformat()
    return dict(id='execution-'+uuid.uuid4().hex,plan_id=plan['id'],schema_version=2,record_kind=kind,
        completion_mode=plan['completion_mode'],completion_effect='none',title=plan['title'],target=plan['target'],
        started_at=stamp,ended_at=None if kind=='session' else stamp,actual_minutes=0,note='',variant='standard',
        planned_minutes=plan.get('target_minutes') or plan.get('estimated_minutes'),planned_date=plan['start_date'],
        timezone=plan['timezone'],business_date=datetime.fromisoformat(stamp).astimezone(ZoneInfo(plan['timezone'])).date().isoformat(),
        date_basis='actual_start' if kind=='session' else 'actual_confirmation',outcome='running' if kind=='session' else 'completed')


def save_fact(c,record):
    c.execute('INSERT INTO action_executions VALUES (?,?,?,?)',(record['id'],record['plan_id'],record['outcome'],encoded(record)))


def mark_complete(plan,record):
    record['completion_effect']='complete'
    plan.update(status='completed',completed_at=record['ended_at'],completion_record_id=record['id'])


def complete_fact(c,plan,source_event=None):
    record=make_fact(plan,'completion',source_event['confirmed_at'] if source_event else None)
    if source_event:
        record.update(source_event_id=source_event['event_id'],recorded_at=clock().isoformat())
        if source_event.get('origin_action_id'):
            record['planned_date']=source_event.get('planned_date_at_confirmation')
            record['timezone']=source_event.get('timezone_at_confirmation') or plan['timezone']
            record['business_date']=datetime.fromisoformat(source_event['confirmed_at']).astimezone(ZoneInfo(record['timezone'])).date().isoformat()
    mark_complete(plan,record);save_fact(c,record)
    return record


def reconcile_event(c,plan,event_id=None):
    executable(c,plan)
    if (active(c) or {}).get('plan_id')==plan['id']:fail(409,'请先保存当前投入再核对。','RUNNING_CONFLICT')
    events=[json.loads(r[0]) for r in c.execute('SELECT data FROM action_content_events ORDER BY id')]
    if event_id and not any(e['event_id']==event_id for e in events):fail(404,'确认回执不存在。')
    for event in sorted(events,key=lambda e:e['confirmed_at'],reverse=True):
        if event_id and event['event_id']!=event_id:continue
        if not same_target(event['normalized_target'],plan['target']) or datetime.fromisoformat(event['confirmed_at'])<datetime.fromisoformat(plan['created_at']):continue
        if event.get('consumed_by') and event['consumed_by']!=plan['id']:continue
        confirmed=datetime.fromisoformat(event['confirmed_at']).astimezone(ZoneInfo(plan['timezone'])).date().isoformat()
        origin=event.get('origin_action_id')
        if origin and origin!=plan['id']:continue
        if not origin and plan['start_date']!=confirmed:continue
        if not plan['start_date'] or plan['start_date']>confirmed:continue
        record=complete_fact(c,plan,event)
        event['consumed_by']=plan['id']
        c.execute('UPDATE action_content_events SET data=? WHERE id=?',(encoded(event),event['event_id']))
        plan['reminder_at']=None
        return record
    fail(409,'未找到本次确认，请打开内容再次明确确认。','COMPLETION_EVIDENCE_MISSING')


def content_completed(target,event_id=None):
    if not event_id:return []
    with connection(True) as c:
        event=c.execute('SELECT data FROM action_content_events WHERE id=?',(event_id,)).fetchone()
        if not event:fail(404,'确认回执不存在。')
        event=json.loads(event[0])
        if event.get('consumed_by'):return [event['consumed_by']]
        candidates=[public(r) for r in c.execute('SELECT * FROM action_plans')]
        for plan in candidates:
            if plan['status']!='active' or plan['completion_mode']!='content' or not same_target(plan['target'],target):continue
            # A savepoint prevents a rejected candidate consuming part of an event.
            c.execute('SAVEPOINT content_match')
            try:reconcile_event(c,plan,event_id)
            except ActionError:
                c.execute('ROLLBACK TO SAVEPOINT content_match');continue
            plan.update(revision=plan['revision']+1,updated_at=clock().isoformat());write(c,plan)
            return [plan['id']]
        return []


def with_content_completion(result,target,event_id=None):
    if not event_id:return result
    try:
        completed=content_completed(target,event_id)
        return {**result,'source_event_id':event_id,'completed_arrangements':completed,
                **({'arrangement_sync_error':'本次确认已保存；尚未匹配完成安排，可先保存投入后核对。'} if not completed else {})}
    except Exception:
        return {**result,'source_event_id':event_id,'arrangement_sync_error':'内容已保存，安排同步待核对，请稍后重试。'}


def mutate(pid,body):
    with connection(True) as c:
        def work():
            plan=get(c,pid)
            if plan['revision']!=body.revision:fail(409,'计划已在其他页面更新，输入保留，请核对。','REVISION_CONFLICT')
            action=body.action;running=active(c);own=running and running['plan_id']==pid;result={}
            if plan['status']=='archived' or (plan['status']=='completed' and action!='reopen'):
                fail(409,'该行动已经完成或归档，请复制新行动。')
            if own and action!='finish':fail(409,'请先结束或保存当前执行。','RUNNING_CONFLICT')
            if action in ('start','complete-time','complete','reconcile','reconcile-content'):
                if plan['status']!='active':fail(409,'请先恢复行动。')
                if plan['period']=='day':executable(c,plan)
            if action=='edit':
                if not body.fields:fail(422,'请提供编辑字段。')
                fields=body.fields.model_dump(mode='json')
                if plan['period']=='day' and (fields['start_date']!=plan['start_date'] or fields['end_date']!=plan['end_date']):
                    fail(422,'请使用改期操作调整日期。')
                if facts(c,pid) and any(fields[k]!=plan.get(k) for k in ('completion_mode','target','target_minutes','minimum_minutes')):
                    fail(409,'已有执行事实，完成方式、内容和阈值已锁定，请复制新行动。')
                validate_parent(c,fields,plan);plan.update(fields,reminder_at=due_at(fields))
            elif action=='reschedule':
                if plan['period']!='day' or plan['status'] not in ('active','paused') or 'date' not in body.model_fields_set:
                    fail(422,'请选择日行动和日期。')
                values={name:plan[name] for name in PlanFields.model_fields if name in plan}
                values.update(start_date=body.date,end_date=body.date)
                if body.date is None:values.update(at=None,reminder=False)
                fields=PlanFields.model_validate(values).model_dump(mode='json')
                validate_parent(c,fields,plan);plan.update(fields,reminder_at=due_at(fields))
            elif action=='reopen':
                if plan['completion_mode']!='check':fail(422,'只有勾选事项可撤销完成。')
                if plan['status']!='completed':fail(409,'事项尚未完成。')
                old=plan.get('completion_record_id') or next((r['id'] for r in reversed(facts(c,pid)) if r['outcome']=='completed'),None)
                record=make_fact(plan,'reversal');record.update(outcome='reopened',completion_effect='reopen',reverses_record_id=old)
                save_fact(c,record);result['execution']=record
                plan.update(status='active',completed_at=None,completion_record_id=None)
            elif action in ('pause','resume','archive','cancel','complete'):
                if action=='resume' and plan['status']!='paused' or action in ('pause','complete') and plan['status']!='active':
                    fail(409,'当前状态不允许该操作。')
                ids={pid}
                descendants=[public(r) for r in c.execute('SELECT * FROM action_plans')]
                for _ in range(4):ids|={p['id'] for p in descendants if p.get('parent_id') in ids}
                if running and running['plan_id'] in ids:fail(409,'请先保存下级正在执行的行动。','RUNNING_CONFLICT')
                if action=='complete' and plan['period']=='day':
                    if plan['completion_mode']!='check':fail(422,'请按该行动的完成标准确认。')
                    result['execution']=complete_fact(c,plan)
                plan['status']={'pause':'paused','resume':'active','archive':'archived','cancel':'archived','complete':'completed'}[action]
                if plan['status'] in ('paused','archived','completed'):plan['reminder_at']=None
                elif action=='resume':plan['reminder_at']=due_at(plan)
            elif action=='start':
                if plan['period']!='day' or plan['completion_mode']=='check':fail(422,'勾选事项无需计时。')
                if running:fail(409,'已有行动正在执行，请先保存。','RUNNING_CONFLICT')
                if body.variant=='minimum' and not plan.get('minimum_minutes'):fail(422,'该行动未设置起步时长。')
                record=make_fact(plan);record['variant']=body.variant
                if body.variant=='minimum':record['planned_minutes']=plan['minimum_minutes']
                save_fact(c,record);result['execution']=record
            elif action=='finish':
                if not own or body.execution_id!=running['id']:fail(409,'该次执行已经结束或发生变化。')
                if body.outcome=='completed' and not body.actual_minutes:fail(422,'请确认本次实际分钟；未执行可中断保存。')
                record=fact_public(running);outcome=body.outcome
                if outcome!='interrupted':
                    if plan['completion_mode']=='content':outcome='recorded'
                    else:
                        total=sum(r['actual_minutes'] for r in facts(c,pid) if r['outcome']!='running' and r['record_kind']=='session')+body.actual_minutes
                        outcome='completed' if total>=plan['target_minutes'] else ('minimum' if plan.get('minimum_minutes') and body.actual_minutes>=plan['minimum_minutes'] else 'partial')
                record.update(ended_at=clock().isoformat(),actual_minutes=body.actual_minutes,note=body.note,outcome=outcome)
                if outcome=='completed':mark_complete(plan,record);plan['reminder_at']=None
                c.execute('UPDATE action_executions SET state=?,data=? WHERE id=?',(outcome,encoded(record),record['id']))
                result['execution']=record
            elif action=='complete-time':
                if plan['completion_mode']!='time' or plan['period']!='day':fail(422,'请选择计时行动。')
                total=sum(r['actual_minutes'] for r in facts(c,pid) if r['outcome']!='running' and r['record_kind']=='session')
                if total<plan['target_minutes']:fail(422,'累计确认投入尚未达标。')
                result['execution']=complete_fact(c,plan);plan['reminder_at']=None
            elif action in ('reconcile','reconcile-content'):
                if plan['completion_mode']!='content':fail(422,'请选择内容行动。')
                result['execution']=reconcile_event(c,plan,body.source_event_id)
            elif action=='snooze':
                if not plan.get('reminder_at') or not plan['reminder'] or plan['status']!='active':fail(409,'当前没有待处理提醒。')
                plan['reminder_at']=(max(clock(),datetime.fromisoformat(plan['reminder_at']))+timedelta(minutes=body.snooze_minutes)).isoformat()
            else:fail(422,'不支持的操作。')
            plan.update(revision=plan['revision']+1,updated_at=clock().isoformat());write(c,plan)
            return {**result,'plan':plan}
        return operation(c,body.key,{'pid':pid,**body.model_dump(mode='json')},work)


def listing():
    with connection() as c:
        plans = [public(row) for row in c.execute('SELECT * FROM action_plans')]
        by_id = {p['id']: p for p in plans}
        records=facts(c)
        running = active(c)
    for plan in plans:
        descendants = {plan['id']}
        for _ in range(4):
            descendants |= {p['id'] for p in plans if p.get('parent_id') in descendants}
        plan['progress']=progress_for(records,descendants)
        ancestor = plan
        plan['blocked'] = False
        while ancestor.get('parent_id'):
            ancestor = by_id.get(ancestor['parent_id'])
            if ancestor is None or ancestor['status'] != 'active':
                plan['blocked'] = True
                break
    return {'action_schema_version':2,'capabilities':{'nullable_schedule':True,'completion_modes':['time','content','check'],'content_receipts':['article','plan'],'actual_fact_dates':True},'plans': sorted(plans, key=lambda p: (p['start_date'] or '9999', p['at'] or '', p['id'])), 'execution': running,
            'server_time': clock().isoformat(), 'reminder_delivery': 'foreground-and-calendar'}


def calendar(pid):
    with connection() as c:
        plan = get(c, pid)
        ancestor = plan
        while ancestor.get('parent_id'):
            ancestor = get(c, ancestor['parent_id'])
            if ancestor['status'] != 'active':
                fail(409, '上级计划已暂停或结束，暂不导出提醒。')
    if plan['period'] != 'day' or plan['status'] != 'active':
        fail(409, '请选择待执行日行动导出日历。')
    if not plan.get('reminder_at'): fail(422,'设置具体时间后可添加日历。')
    start = datetime.fromisoformat(plan['reminder_at'])
    end = start + timedelta(minutes=plan.get('target_minutes') or plan.get('estimated_minutes') or 20)
    def escape(value):
        return value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '').replace(';', '\\;').replace(',', '\\,')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Grow//Action Plans//ZH', 'BEGIN:VEVENT',
             'UID:' + pid + '@grow', 'DTSTAMP:' + clock().strftime('%Y%m%dT%H%M%SZ'),
             'DTSTART:' + start.strftime('%Y%m%dT%H%M%SZ'), 'DTEND:' + end.strftime('%Y%m%dT%H%M%SZ'),
             'SUMMARY:' + escape(plan['title']), 'DESCRIPTION:' + escape('打开知行成长继续行动。' + plan['if_then'])]
    if plan['reminder']:
        lines += ['BEGIN:VALARM', 'TRIGGER:PT0S', 'ACTION:DISPLAY', 'DESCRIPTION:行动计划提醒', 'END:VALARM']
    lines += ['END:VEVENT', 'END:VCALENDAR']
    # Fold by UTF-8 octets, without splitting a multibyte character (RFC 5545).
    folded = []
    for line in lines:
        part = ''
        for char in line:
            if len((part + char).encode()) > 74:
                folded.append(part);part = ' '
            part += char
        folded.append(part)
    return '\r\n'.join(folded) + '\r\n'


class Claim(Input):
    device_id: str = Field(pattern=r'^[a-zA-Z0-9-]{8,80}$')
    reminder_at: str = Field(max_length=80)


def register(app):
    @app.exception_handler(ActionError)
    async def action_error(request,exc):
        return JSONResponse({'detail':exc.detail,'code':exc.code,**exc.extra},status_code=exc.status_code)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        if not request.url.path.startswith('/api/action-plans'):
            from fastapi.exception_handlers import request_validation_exception_handler
            return await request_validation_exception_handler(request,exc)
        return JSONResponse({'detail':'请检查填写字段。','code':'VALIDATION_ERROR','errors':[{k:v for k,v in e.items() if k in ('loc','msg','type')} for e in exc.errors()]},status_code=422)

    router = APIRouter(prefix='/api/action-plans')

    @router.get('')
    def read():
        return listing()

    @router.post('/schedules')
    def arrange(body: Schedule):
        return schedule(body)

    @router.post('')
    def add(body: NewPlan):
        return create(body)

    @router.post('/{pid}/operations')
    def change(pid: str, body: Mutation):
        return mutate(pid, body)

    @router.get('/records')
    def records(page: int = Query(default=1, ge=1, le=100000), plan_id: str | None = Query(default=None, max_length=80)):
        with connection() as c:
            if plan_id:
                get(c, plan_id)
            where = ' WHERE plan_id=?' if plan_id else ''
            params = [plan_id] if plan_id else []
            total = c.execute('SELECT count(*) FROM action_executions' + where, params).fetchone()[0]
            rows = c.execute('SELECT data FROM action_executions' + where + " ORDER BY data::jsonb->>'started_at' DESC,id DESC LIMIT 30 OFFSET ?", [*params, (page-1)*30]).fetchall()
            return {'records': [fact_public(json.loads(r[0])) for r in rows], 'total': total, 'page': page}

    @router.get('/requests/{key}')
    def request_result(key: str):
        if len(key) > 160:
            fail(422, '请求编号无效。')
        with connection() as c:
            row = c.execute('SELECT result FROM action_operations WHERE key=?', (key,)).fetchone()
            return {'found': bool(row), 'result': json.loads(row[0]) if row else None}

    @router.get('/{pid}/calendar.ics')
    def export(pid: str):
        return Response(calendar(pid), media_type='text/calendar', headers={'Content-Disposition': 'attachment; filename="grow-action.ics"'})

    @router.post('/{pid}/reminder-claim')
    def claim(pid: str, body: Claim):
        with connection(True) as c:
            plan = get(c, pid)
            local = clock().astimezone(ZoneInfo(plan['timezone']))
            eligible = (plan['period'] == 'day' and plan['status'] == 'active' and plan['reminder'] and
                        bool(plan.get('reminder_at')) and plan['reminder_at'] == body.reminder_at and datetime.fromisoformat(plan['reminder_at']) <= clock() and
                        local.date().isoformat() == plan['start_date'] and 8 <= local.hour < 22 and
                        not (active(c) or {}).get('plan_id') == pid)
            ancestor = plan
            while eligible and ancestor.get('parent_id'):
                ancestor = get(c, ancestor['parent_id']);eligible = ancestor['status'] == 'active'
            if not eligible:
                return {'notify': False}
            identity = hashlib.sha256(encoded([body.device_id, pid, body.reminder_at]).encode()).hexdigest()
            row = c.execute('INSERT INTO action_reminder_claims VALUES (?,?) ON CONFLICT(key) DO NOTHING RETURNING key', (identity, clock().isoformat())).fetchone()
            return {'notify': bool(row)}

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if request.url.path.startswith('/api/action-plans') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = f'{request.url.scheme}://{request.url.netloc}'
            if request.headers.get('X-Copilot-Request') != '1' or request.headers.get('Origin', origin) != origin or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                return Response('需要同源请求。', status_code=403)
            if request.headers.get('X-Grow-Action-Schema') != '2':
                return JSONResponse({'detail':'行动服务合同需升级，请刷新后重试。','code':'CONTRACT_UPGRADE_REQUIRED'},status_code=409)
            length = request.headers.get('Content-Length', '0')
            if not length.isdecimal() or int(length) > 30000:
                return Response('请求内容过长。', status_code=413)
        response = await call_next(request)
        if request.url.path.startswith('/api/action-plans'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    from action_reviews import register as register_reviews
    register_reviews(router)
    app.include_router(router)
    from action_link import register as register_link
    register_link(app)
