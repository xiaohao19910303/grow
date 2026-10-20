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
from fastapi.responses import Response
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
CREATE TABLE IF NOT EXISTS action_reminder_claims (key TEXT PRIMARY KEY,claimed_at TEXT NOT NULL);
'''


def clock():
    return datetime.now(timezone.utc)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fail(status, message):
    raise HTTPException(status, message)


@contextmanager
def connection(write=False, allow_link=False):
    with db.connect() as c:
        tables=c.execute("SELECT to_regclass('action_link_state') AS link,to_regclass('action_reviews') AS reviews").fetchone()
        if tables[0] is None or tables[1] is None:
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
    start_date: date
    end_date: date
    timezone: str = Field(default='Asia/Shanghai', max_length=80)
    parent_id: str | None = Field(default=None, max_length=80)
    target_minutes: int = Field(default=20, ge=1, le=1440, strict=True)
    target_count: int = Field(default=1, ge=1, le=1000, strict=True)
    minimum_minutes: int = Field(default=5, ge=1, le=1440, strict=True)
    at: str = Field(default='21:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    reminder: bool = False
    reason: str = Field(default='', max_length=1000)
    if_then: str = Field(default='', max_length=1000)
    target: StudyTarget = Field(default_factory=StudyTarget)
    completion_mode: Literal['time', 'content', 'check'] = 'time'

    @model_validator(mode='after')
    def valid_period(self):
        self.title = self.title.strip()
        self.horizon = self.horizon or ('long' if self.period == 'year' else 'short')
        if not self.title or self.end_date < self.start_date or (self.end_date - self.start_date).days > 366:
            raise ValueError('标题和计划日期范围无效。')
        if self.period == 'day' and self.target_count != 1:
            raise ValueError('每个日行动对应一次达标，请拆分创建多次行动。')
        if self.period == 'day' and self.start_date != self.end_date:
            raise ValueError('日行动只能安排在一天。')
        if self.completion_mode != 'time' and self.period != 'day':
            raise ValueError('只有日行动可以按内容或勾选完成。')
        if self.completion_mode == 'content' and self.target.kind in ('library', 'book'):
            raise ValueError('请选择具体文章或课程。')
        if self.period == 'week' and (self.end_date - self.start_date).days > 6:
            raise ValueError('周计划最多包含七天。')
        if self.period == 'month' and (self.start_date.year, self.start_date.month) != (self.end_date.year, self.end_date.month):
            raise ValueError('月计划的日期需在同一个月。')
        if self.period == 'year' and self.start_date.year != self.end_date.year:
            raise ValueError('年目标的日期需在同一年。')
        if self.minimum_minutes > self.target_minutes:
            raise ValueError('起步时长不能超过标准时长。')
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
    action: Literal['edit', 'pause', 'resume', 'archive', 'complete', 'start', 'finish', 'snooze', 'reschedule', 'cancel', 'reopen', 'reconcile']
    date: CalendarDate | None = None
    fields: PlanFields | None = None
    variant: Literal['standard', 'minimum'] = 'standard'
    execution_id: str | None = Field(default=None, max_length=80)
    outcome: Literal['completed', 'interrupted'] = 'completed'
    actual_minutes: int = Field(default=0, ge=0, le=1440, strict=True)
    note: str = Field(default='', max_length=2000)
    snooze_minutes: int = Field(default=15, ge=5, le=120, strict=True)


def public(row):
    data = json.loads(row['data'])
    return {**data, 'completion_mode': data.get('completion_mode', 'time'), 'horizon': data.get('horizon') or ('long' if data['period'] == 'year' else 'short'), 'id': row['id'], 'revision': row['revision']}


def same_target(left, right):
    return StudyTarget.model_validate(left) == StudyTarget.model_validate(right)


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
        if not parent['start_date'] <= fields['start_date'] <= fields['end_date'] <= parent['end_date'] or fields['timezone'] != parent['timezone']:
            fail(422, '子计划的日期和时区需在上级计划范围内。')
    target = fields['target']
    if target['kind'] in ('plan', 'article'):
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
    if duplicate_schedule(c, fields, existing['id'] if existing else None):
        fail(409, '这份内容在该日期已有安排，请查看或调整已有安排。')


def create(body):
    with connection(True) as c:
        def work():
            if c.execute('SELECT count(*) FROM action_plans').fetchone()[0] + max(1, len(body.repeat_dates)) > 1000:
                fail(422, '计划数量已达首版上限，请先整理历史计划。')
            dates = body.repeat_dates or [body.start_date]
            if body.repeat_dates and (body.period != 'day' or len(set(dates)) != len(dates) or (max(dates) - min(dates)).days > 6 or body.start_date not in dates):
                fail(422, '重复日行动请选择同一七天内不重复的日期，并包含首日。')
            result = []
            for day in sorted(dates):
                fields = body.model_dump(mode='json', exclude={'key', 'repeat_dates'})
                if body.repeat_dates:
                    fields.update(start_date=day.isoformat(), end_date=day.isoformat())
                validate_parent(c, fields)
                pid = 'action-' + uuid.uuid4().hex
                plan = {**fields, 'id': pid, 'revision': 1, 'status': 'active', 'created_at': clock().isoformat(),
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
    date: CalendarDate
    timezone: str = Field(default='Asia/Shanghai', max_length=80)
    target_minutes: int = Field(default=20, ge=1, le=1440, strict=True)
    key: str = Field(min_length=8, max_length=160)

    @model_validator(mode='after')
    def valid_content(self):
        if self.target.kind in ('library','book'):
            raise ValueError('日期安排请选择具体文章或课程。')
        try:
            ZoneInfo(self.timezone)
        except (ValueError,ZoneInfoNotFoundError):
            raise ValueError('时区无效。') from None
        if not self.title.strip():
            raise ValueError('请填写内容标题。')
        return self


def schedule(body):
    fields = NewPlan(title=body.title, period='day', start_date=body.date, end_date=body.date,
                     timezone=body.timezone, target=body.target, target_minutes=body.target_minutes,
                     minimum_minutes=min(5, body.target_minutes), completion_mode='content', key=body.key)
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
            plan = {**data, 'id': pid, 'revision': 1, 'status': 'active', 'created_at': clock().isoformat(),
                    'updated_at': clock().isoformat(), 'reminder_at': due_at(data)}
            c.execute('INSERT INTO action_plans VALUES (?,?,1)', (pid, encoded(plan)))
            return {'plan': plan, 'existing': False}
        return operation(c, body.key, {'op': 'schedule', **body.model_dump(mode='json')}, work)


def complete_fact(c, plan, running=None):
    """An explicit content/check confirmation is a fact, not guessed minutes."""
    stamp = clock().isoformat()
    execution = running if running and running['plan_id'] == plan['id'] else None
    if execution:
        # Actual minutes require a separate user confirmation; elapsed wall time
        # can include idle/background time and is never used as actual time.
        execution.update(outcome='completed', ended_at=stamp, actual_minutes=0,
                         completion_mode=plan['completion_mode'])
        c.execute("UPDATE action_executions SET state='completed',data=? WHERE id=?", (encoded(execution), execution['id']))
    else:
        execution = dict(id='execution-' + uuid.uuid4().hex, plan_id=plan['id'], title=plan['title'],
                         started_at=stamp, ended_at=stamp, variant='standard', planned_minutes=plan['target_minutes'],
                         actual_minutes=0, outcome='completed', note='', business_date=plan['start_date'],
                         timezone=plan['timezone'], target=plan['target'], completion_mode=plan['completion_mode'])
        c.execute("INSERT INTO action_executions VALUES (?,?,'completed',?)", (execution['id'], plan['id'], encoded(execution)))
    plan.update(status='completed', updated_at=stamp)
    return execution


def content_completed(target):
    """Called only after an explicit source completion has saved successfully."""
    with db.connect() as c:
        if c.execute("SELECT to_regclass('action_plans')").fetchone()[0] is None:
            return []
    with connection(True) as c:
        running = active(c)
        plans = [public(row) for row in c.execute('SELECT * FROM action_plans')]
        by_id = {p['id']: p for p in plans}
        running_content = by_id.get(running['plan_id']) if running else None
        if running_content and (running_content['completion_mode'] != 'content' or not same_target(running_content['target'], target)):
            running_content = None
        completed = []
        for plan in plans:
            if (plan['completion_mode'] != 'content' or plan['status'] != 'active'
                    or not same_target(plan['target'], target)):
                continue
            today = clock().astimezone(ZoneInfo(plan['timezone'])).date().isoformat()
            if running_content and plan['id'] != running_content['id']:
                continue
            if plan['start_date'] != today and not (running and running['plan_id'] == plan['id']):
                continue
            ancestor = plan
            while ancestor.get('parent_id') and ancestor['status'] == 'active':
                ancestor = by_id[ancestor['parent_id']]
            if ancestor['status'] != 'active':
                continue
            complete_fact(c, plan, running)
            plan['revision'] += 1
            write(c, plan)
            completed.append(plan['id'])
        return completed


def with_content_completion(result, target):
    """Source save succeeded even if a later schedule refresh is unavailable."""
    try:
        content_completed(target)
        return result
    except Exception:
        return {**result, 'arrangement_sync_error': '内容完成记录已保存，日期安排暂未同步，请在今日点击核对完成。'}


def content_is_complete(c, target):
    kind = target['kind']
    table = {'article':'reading_records', 'plan':'learning_lessons', 'renzhi':'copilot_learning_records',
             'yingyu':'study_learning_records', 'biaoda':'study_learning_records'}.get(kind)
    if not table or c.execute('SELECT to_regclass(?)', (table,)).fetchone()[0] is None:
        return False
    if kind == 'article':
        row = c.execute('SELECT data FROM reading_records WHERE id=?', (target['course'],)).fetchone()
        return bool(row and json.loads(row[0]).get('read'))
    if kind == 'plan':
        row = c.execute('SELECT data FROM learning_lessons WHERE plan_id=? AND lesson_no=?', (target['plan_id'], target['lesson_no'])).fetchone()
        return bool(row and json.loads(row[0]).get('learning_state') == 'completed')
    if kind == 'renzhi':
        return bool(c.execute("SELECT 1 FROM copilot_learning_records WHERE module_id='renzhi' AND round_id=1 AND lesson_no=?", (target['lesson_no'],)).fetchone())
    return bool(c.execute('SELECT 1 FROM study_learning_records WHERE module_id=? AND filename=?', (kind, target['course'])).fetchone())


def mutate(pid, body):
    with connection(True) as c:
        def work():
            plan = get(c, pid)
            if plan['revision'] != body.revision:
                fail(409, '计划已被另一页面更新，当前输入保留，请刷新后核对。')
            running = active(c)
            own_running = running and running['plan_id'] == pid
            if body.action in ('edit', 'pause', 'archive', 'cancel', 'reschedule', 'reopen') and own_running:
                fail(409, '请先结束或保存中断的执行，再调整计划。')
            result = {}
            if body.action == 'reconcile':
                if plan['completion_mode'] != 'content' or plan['status'] != 'active':
                    fail(422, '请选择待完成的内容安排。')
                if plan['start_date'] > clock().astimezone(ZoneInfo(plan['timezone'])).date().isoformat():
                    fail(422, '未来安排不能提前核对完成，请先改期。')
                ancestor = plan
                while ancestor.get('parent_id'):
                    ancestor = get(c, ancestor['parent_id'])
                    if ancestor['status'] != 'active':
                        fail(409, '请先恢复上级计划。')
                if not content_is_complete(c, plan['target']):
                    fail(409, '原内容尚未确认读完／学完，请先打开内容完成确认。')
                result['execution'] = complete_fact(c, plan, running)
            elif body.action == 'edit':
                if not body.fields or plan['status'] == 'archived':
                    fail(422, '请提供可编辑的计划内容。')
                fields = body.fields.model_dump(mode='json')
                validate_parent(c, fields, plan)
                plan.update(fields, reminder_at=due_at(fields))
            elif body.action == 'reschedule':
                if plan['period'] != 'day' or plan['status'] not in ('active', 'paused') or not body.date:
                    fail(422, '请选择待执行安排和有效日期。')
                fields = PlanFields.model_validate({**{name: plan[name] for name in PlanFields.model_fields if name in plan},
                    'start_date': body.date, 'end_date': body.date}).model_dump(mode='json')
                validate_parent(c, fields, plan)
                plan.update(fields, reminder_at=due_at(fields))
            elif body.action == 'cancel':
                if plan['period'] != 'day' or plan['status'] not in ('active', 'paused'):
                    fail(409, '只能取消尚未完成的日程安排。')
                plan['status'] = 'archived'
            elif body.action == 'reopen':
                if plan['completion_mode'] != 'check' or plan['status'] != 'completed':
                    fail(422, '只有已完成待办可以撤销勾选。')
                for row in c.execute("SELECT * FROM action_executions WHERE plan_id=? AND state='completed'", (pid,)):
                    fact = json.loads(row['data']); fact['outcome'] = 'reopened'
                    c.execute("UPDATE action_executions SET state='reopened',data=? WHERE id=?", (encoded(fact), row['id']))
                plan['status'] = 'active'
            elif body.action in ('pause', 'resume', 'archive', 'complete'):
                desired = {'pause': 'paused', 'resume': 'active', 'archive': 'archived', 'complete': 'completed'}[body.action]
                if body.action == 'complete' and plan['period'] == 'day':
                    if plan['completion_mode'] != 'check':
                        fail(422, '请在原文章／课程确认完成；计时目标请记录实际执行。')
                    if plan['start_date'] > clock().astimezone(ZoneInfo(plan['timezone'])).date().isoformat():
                        fail(422, '未来待办请先改期再完成。')
                if plan['status'] == 'archived' or body.action == 'resume' and plan['status'] != 'paused' or body.action in ('pause', 'complete') and plan['status'] != 'active':
                    fail(409, '这个计划当前无法进行该操作。')
                descendants = [public(r) for r in c.execute('SELECT * FROM action_plans')]
                todo = {pid}
                for _ in range(4):
                    todo |= {p['id'] for p in descendants if p.get('parent_id') in todo}
                if running and running['plan_id'] in todo:
                    fail(409, '请先结束子计划正在进行的执行。')
                if body.action == 'complete' and plan['period'] == 'day':
                    result['execution'] = complete_fact(c, plan)
                plan['status'] = desired
            elif body.action == 'start':
                if plan['period'] != 'day' or plan['status'] != 'active':
                    fail(409, '请选择一个待执行的日行动。')
                ancestor = plan
                while ancestor.get('parent_id'):
                    ancestor = get(c, ancestor['parent_id'])
                    if ancestor['status'] != 'active':
                        fail(409, '上级计划已暂停或归档，请先恢复。')
                if running:
                    fail(409, '已有一项执行正在进行，请先结束或中断保存。')
                if date.fromisoformat(plan['start_date']) > clock().astimezone(ZoneInfo(plan['timezone'])).date():
                    fail(422, '这是未来的日行动，请先调整日期再开始。')
                execution = {'id': 'execution-' + uuid.uuid4().hex, 'plan_id': pid, 'title': plan['title'],
                             'started_at': clock().isoformat(), 'ended_at': None, 'variant': body.variant,
                             'planned_minutes': plan['minimum_minutes'] if body.variant == 'minimum' else plan['target_minutes'],
                             'actual_minutes': 0, 'outcome': 'running', 'note': '', 'business_date': plan['start_date'],
                             'timezone': plan['timezone'], 'target': plan['target']}
                c.execute("INSERT INTO action_executions VALUES (?,?,'running',?)", (execution['id'], pid, encoded(execution)))
                result['execution'] = execution
            elif body.action == 'finish':
                if not own_running or body.execution_id != running['id']:
                    fail(409, '该次执行已结束或发生变化，请刷新记录。')
                if body.outcome == 'completed' and not body.actual_minutes:
                    fail(422, '请填写实际执行分钟，未执行可选择中断保存。')
                outcome = body.outcome
                if outcome == 'completed' and plan['completion_mode'] == 'content':
                    outcome = 'partial'
                elif outcome == 'completed' and body.actual_minutes < plan['target_minutes']:
                    outcome = 'minimum' if body.actual_minutes >= plan['minimum_minutes'] else 'partial'
                running.update(ended_at=clock().isoformat(), actual_minutes=body.actual_minutes, note=body.note, outcome=outcome)
                c.execute('UPDATE action_executions SET state=?,data=? WHERE id=?', (outcome, encoded(running), running['id']))
                if outcome == 'completed':
                    plan['status'] = 'completed'
                result['execution'] = running
            elif body.action == 'snooze':
                if plan['period'] != 'day' or plan['status'] != 'active' or not plan['reminder']:
                    fail(409, '当前计划没有待处理的提醒。')
                plan['reminder_at'] = (max(clock(), datetime.fromisoformat(plan['reminder_at'])) + timedelta(minutes=body.snooze_minutes)).isoformat()
            plan.update(revision=plan['revision'] + 1, updated_at=clock().isoformat())
            write(c, plan)
            return {**result, 'plan': plan}
        return operation(c, body.key, {'pid': pid, **body.model_dump(mode='json')}, work)


def listing():
    with connection() as c:
        plans = [public(row) for row in c.execute('SELECT * FROM action_plans')]
        by_id = {p['id']: p for p in plans}
        facts = {row[0]: {'minutes': row[1], 'completed': row[2], 'minimum': row[3], 'interrupted': row[4]}
                 for row in c.execute("""SELECT plan_id,
                    COALESCE(sum((data::jsonb->>'actual_minutes')::int),0) AS minutes,
                    count(*) FILTER (WHERE state='completed') AS completed,
                    count(*) FILTER (WHERE state IN ('minimum','partial')) AS minimum,
                    count(*) FILTER (WHERE state='interrupted') AS interrupted
                    FROM action_executions WHERE state<>'running' GROUP BY plan_id""")}
        running = active(c)
    for plan in plans:
        descendants = {plan['id']}
        for _ in range(4):
            descendants |= {p['id'] for p in plans if p.get('parent_id') in descendants}
        plan['progress'] = {name: sum(facts.get(pid, {}).get(name, 0) for pid in descendants)
                            for name in ('minutes', 'completed', 'minimum', 'interrupted')}
        ancestor = plan
        plan['blocked'] = False
        while ancestor.get('parent_id'):
            ancestor = by_id.get(ancestor['parent_id'])
            if ancestor is None or ancestor['status'] != 'active':
                plan['blocked'] = True
                break
    return {'plans': sorted(plans, key=lambda p: (p['start_date'], p['at'], p['id'])), 'execution': running,
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
    start = datetime.fromisoformat(plan['reminder_at'])
    end = start + timedelta(minutes=plan['target_minutes'])
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
            return {'records': [json.loads(r[0]) for r in rows], 'total': total, 'page': page}

    @router.get('/requests/{key}')
    def request_result(key: str):
        if len(key) > 160:
            fail(422, '请求编号无效。')
        with connection(True) as c:
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
                        plan['reminder_at'] == body.reminder_at and datetime.fromisoformat(plan['reminder_at']) <= clock() and
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
