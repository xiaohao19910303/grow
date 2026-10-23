"""R04 metadata and small-step facts; never rewrite completed execution history."""
from datetime import datetime
import json

import action_plans as actions
from .contracts import activity_date
from . import service


def empty_context(variant='standard'):
    return dict(rhythm_variant=variant, minimum_step_snapshot='', focus_day_id=None,
                focus_plan_id_snapshot=None, focus_selected_at_snapshot=None)


def focus_context(c, plan, stamp, variant=None):
    result = empty_context(variant or 'standard')
    prefs = service.preferences(c, stamp)['preferences']
    if not prefs['enabled']:
        return result
    focus = service.focus_on(c, activity_date(stamp, prefs['timezone']))
    if (not focus or focus['plan_id'] != plan['id'] or focus.get('rest')
            or datetime.fromisoformat(focus['selected_at']) > stamp):
        return result
    result.update(focus_day_id=focus['id'], focus_plan_id_snapshot=plan['id'],
                  focus_selected_at_snapshot=focus['selected_at'], rhythm_variant=variant or focus['mode'])
    if result['rhythm_variant'] == 'minimum':
        result['minimum_step_snapshot'] = focus.get('minimum_step', '')
    return result


def source_context(c, target, origin, stamp):
    """Capture before source publication, so delayed sync never consults new focus."""
    row = c.execute('SELECT data FROM action_link_state WHERE id=1').fetchone()
    if row and json.loads(row[0]).get('phase') != 'local':
        return empty_context()
    prefs = service.preferences(c, stamp)['preferences']
    focus = service.focus_on(c, activity_date(stamp, prefs['timezone'])) if prefs['enabled'] else None
    if not focus or (origin and origin != focus['plan_id']):
        return empty_context()
    plan = actions.get(c, focus['plan_id'])
    return focus_context(c, plan, stamp) if actions.same_target(plan['target'], target) else empty_context()


def start(c, plan, record, variant):
    record.update(fact_version=2, activity_confirmed=False, activity_at=None,
                  activity_date=None, activity_timezone=record['timezone'],
                  **focus_context(c, plan, datetime.fromisoformat(record['started_at']), variant))


def confirm(record):
    stamp = datetime.fromisoformat(record['ended_at'])
    kind = record['record_kind']
    did_act = ((kind == 'session' and record['actual_minutes'] > 0)
               or kind == 'step'
               or kind == 'completion' and (record['completion_mode'] == 'check'
                   or record['completion_mode'] == 'content' and bool(record.get('source_event_id'))))
    record.update(fact_version=2, activity_at=stamp.isoformat(),
                  activity_date=str(activity_date(stamp, record['timezone'])),
                  activity_timezone=record['timezone'], activity_confirmed=bool(did_act))
    for key, value in empty_context(record.get('variant', 'standard')).items():
        record.setdefault(key, value)


def instant(c, plan, record, source_event=None):
    if source_event is not None:
        # Old source receipts have no start context. Never attach today's choice.
        context = source_event.get('rhythm_snapshot') or empty_context()
    elif record['record_kind'] == 'reversal':
        context = empty_context()
    else:
        context = focus_context(c, plan, datetime.fromisoformat(record['ended_at']))
    record.update(context)
    confirm(record)


def save_step(body):
    with actions.connection(True) as c:
        service.bootstrap(c)
        def work():
            prefs = service.require_enabled(c)
            today = activity_date(actions.clock(), prefs['timezone'])
            focus = service.focus_on(c, today)
            if not focus or focus['id'] != body.focus_day_id or focus['plan_id'] != body.plan_id:
                actions.fail(409, '今日主任务已变化，请刷新后核对。', 'STATE_CONFLICT')
            if focus['mode'] != 'minimum' or focus['minimum_step'] != body.minimum_step:
                actions.fail(409, '最小步骤已变化，请重新确认。', 'STATE_CONFLICT')
            plan = service.focus_plan(c, body.plan_id, today)
            if plan['revision'] != body.plan_revision:
                actions.fail(409, '行动已更新，请刷新后核对。', 'REVISION_CONFLICT')
            if plan['completion_mode'] != 'check':
                actions.fail(422, '只有勾选行动使用无计时的小步骤确认。')
            if actions.active(c):
                actions.fail(409, '请先保存正在执行的行动。', 'RUNNING_CONFLICT')
            record = actions.make_fact(plan, 'step')
            record.update(outcome='partial', variant='minimum', planned_minutes=None,
                          note=body.note, next_step=body.next_step)
            instant(c, plan, record)
            actions.save_fact(c, record)
            plan.update(revision=plan['revision'] + 1, updated_at=actions.clock().isoformat())
            actions.write(c, plan)
            return {'plan': plan, 'execution': record}
        return actions.operation(c, body.key, {'op': 'rhythm.step', **body.model_dump(mode='json')}, work)


def completion_receipts(c, event_id):
    row = c.execute('SELECT data FROM action_content_events WHERE id=?', (event_id,)).fetchone()
    if not row:
        actions.fail(404, '来源确认回执不存在。')
    records = c.execute("""SELECT data FROM action_executions
        WHERE data::jsonb->>'source_event_id'=? AND data::jsonb->>'completion_effect'='complete'
        ORDER BY id""", (event_id,))
    result = []
    for row in records:
        record = json.loads(row[0])
        result.append(dict(plan_id=record['plan_id'], execution_id=record['id'],
                           activity_date=record.get('activity_date') or str(activity_date(
                               datetime.fromisoformat(record['ended_at']), record['timezone']))))
    return result
