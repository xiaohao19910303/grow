"""R03 preferences and daily focus; one transaction/lock with existing actions."""
from datetime import datetime, time
import json
import uuid
from zoneinfo import ZoneInfo

import action_plans as actions
from copilot.core import Problem
from .contracts import PreferencesInput, activity_date, preferences_effective_from
from .schema import initialize


def preference_rows(c):
    if c.execute("SELECT to_regclass('action_rhythm_preferences')").fetchone()[0] is None:
        return []
    return [json.loads(row[0]) for row in c.execute('SELECT data FROM action_rhythm_preferences ORDER BY effective_from')]


def preferences(c, stamp=None):
    stamp = stamp or actions.clock()
    defaults = PreferencesInput(key='defaults', expected_revision=0).model_dump(exclude={'key', 'expected_revision'})
    versions = []
    for row in preference_rows(c):
        versions.extend(row.get('history', []))
        versions.append({k: v for k, v in row.items() if k != 'history'})
    known = [v for v in versions if datetime.fromisoformat(v['updated_at']) <= stamp]
    effective = [v for v in known if datetime.fromisoformat(v['effective_at']) <= stamp]
    active = max(effective, key=lambda v: (datetime.fromisoformat(v['effective_at']), v['revision']), default=None)
    latest = max(known, key=lambda v: v['revision'], default=None)
    current = {**defaults, **(active or {}), 'revision': max((v['revision'] for v in versions), default=0)}
    # Enable/disable and reminder controls are immediate; goals/timezone are weekly.
    if latest:
        current.update({k: latest[k] for k in ('enabled', 'reminder_enabled', 'reminder_time')})
    pending = max((v for v in known if datetime.fromisoformat(v['effective_at']) > stamp),
                  key=lambda v: v['revision'], default=None)
    return {'preferences': current, 'pending_preferences': pending}


def focus_on(c, day):
    if c.execute("SELECT to_regclass('action_focus_days')").fetchone()[0] is None:
        return None
    row = c.execute('SELECT data FROM action_focus_days WHERE local_date=?', (str(day),)).fetchone()
    return json.loads(row[0]) if row else None


def bootstrap(c):
    try:
        initialize(c)
    except Problem as exc:
        actions.fail(exc.status, exc.message, exc.code)


def save_preferences(body):
    with actions.connection(True) as c:
        bootstrap(c)
        def work():
            stamp = actions.clock()
            state = preferences(c, stamp)
            current = state['preferences']
            if current['revision'] != body.expected_revision:
                actions.fail(409, '节奏设置已更新，请刷新后核对。', 'REVISION_CONFLICT')
            weekly_changed = any(getattr(body, k) != current[k] for k in ('timezone', 'weekly_target_days', 'review_weekday'))
            first = current['revision'] == 0
            deferred = not first and (weekly_changed or state['pending_preferences'] is not None)
            day = preferences_effective_from(stamp, body.timezone if first else current['timezone'], first=not deferred)
            effective_at = datetime.combine(day, time.min, ZoneInfo(current['timezone'])).isoformat() if deferred else stamp.isoformat()
            old = next((row for row in preference_rows(c) if row['effective_from'] == day.isoformat()), None)
            data = {**body.model_dump(exclude={'key', 'expected_revision'}),
                    'id': old['id'] if old else 'rhythm-pref-' + uuid.uuid4().hex,
                    'effective_from': day.isoformat(), 'effective_at': effective_at,
                    'revision': current['revision'] + 1, 'updated_at': stamp.isoformat()}
            if old:
                data['history'] = [*old.get('history', []), {k: v for k, v in old.items() if k != 'history'}]
            c.execute('''INSERT INTO action_rhythm_preferences VALUES (?,?,?,?)
                ON CONFLICT(effective_from) DO UPDATE SET data=EXCLUDED.data,revision=EXCLUDED.revision''',
                (data['id'], data['effective_from'], actions.encoded(data), data['revision']))
            return preferences(c, stamp)
        return actions.operation(c, body.key, {'op': 'rhythm.preferences', **body.model_dump(mode='json')}, work)


def require_enabled(c):
    current = preferences(c)['preferences']
    if not current['enabled']:
        actions.fail(409, '请先开启日常节奏。', 'FEATURE_DISABLED')
    return current


def require_today(day, current):
    if str(day) != activity_date(actions.clock(), current['timezone']).isoformat():
        actions.fail(422, '只能修改当前本地日期的主任务；历史和未来日期只读。')


def focus_plan(c, pid, day):
    plan = actions.get(c, pid)
    if plan['period'] != 'day' or plan['start_date'] != str(day):
        actions.fail(422, '请选择已安排到当天的日行动。')
    if plan['status'] != 'active':
        actions.fail(409, '请选择可执行的行动。', 'STATE_CONFLICT')
    actions.executable(c, plan)
    return plan


def persist_focus(c, data):
    c.execute('''INSERT INTO action_focus_days VALUES (?,?,?,?)
        ON CONFLICT(local_date) DO UPDATE SET data=EXCLUDED.data,revision=EXCLUDED.revision''',
        (data['id'], data['local_date'], actions.encoded(data), data['revision']))


def select_focus(body):
    with actions.connection(True) as c:
        bootstrap(c)
        def work():
            current = require_enabled(c)
            require_today(body.date, current)
            old = focus_on(c, body.date)
            if (old['revision'] if old else 0) != body.expected_revision:
                actions.fail(409, '今日一件事已在其他页面更新。', 'REVISION_CONFLICT')
            focus_plan(c, body.plan_id, body.date)
            same = old and old['plan_id'] == body.plan_id
            data = {**body.model_dump(mode='json', exclude={'key', 'expected_revision', 'date'}),
                    'id': old['id'] if old else 'focus-' + uuid.uuid4().hex,
                    'local_date': str(body.date), 'timezone': current['timezone'],
                    'revision': body.expected_revision + 1, 'selected_at': actions.clock().isoformat(),
                    'mode': old['mode'] if same else 'standard',
                    'minimum_step': old.get('minimum_step', '') if same else '',
                    'rest': old.get('rest', False) if same else False}
            persist_focus(c, data)
            from .events import emit
            emit(c, 'focus_selected', 'focus:' + body.key, plan_id=data['plan_id'], focus_day_id=data['id'], revision=data['revision'], activity_date=data['local_date'])
            return {'focus': data}
        return actions.operation(c, body.key, {'op': 'rhythm.focus', **body.model_dump(mode='json')}, work)


def change_mode(fid, body):
    with actions.connection(True) as c:
        bootstrap(c)
        def work():
            current = require_enabled(c)
            row = c.execute('SELECT data FROM action_focus_days WHERE id=?', (fid,)).fetchone()
            if not row:
                actions.fail(404, '今日主任务不存在。')
            focus = json.loads(row[0])
            require_today(focus['local_date'], current)
            if focus['revision'] != body.expected_revision:
                actions.fail(409, '主任务模式已变化，请刷新后核对。', 'REVISION_CONFLICT')
            if body.mode == 'rest':
                if actions.active(c):
                    actions.fail(409, '请先保存正在执行的行动。', 'RUNNING_CONFLICT')
            else:
                focus_plan(c, focus['plan_id'], focus['local_date'])
            focus.update(mode=body.mode, minimum_step=body.minimum_step, rest=body.mode == 'rest',
                         revision=focus['revision'] + 1, updated_at=actions.clock().isoformat())
            persist_focus(c, focus)
            if body.mode in ('minimum', 'rest'):
                from .events import emit
                emit(c, body.mode + '_selected', 'mode:' + body.key, focus_day_id=fid, plan_id=focus['plan_id'], mode=body.mode)
            return {'focus': focus}
        return actions.operation(c, body.key, {'op': 'rhythm.mode', 'focus_id': fid, **body.model_dump(mode='json')}, work)


def today(day=None):
    with actions.connection() as c:
        state = preferences(c)
        current = state['preferences']
        actual_day = activity_date(actions.clock(), current['timezone'])
        day = day or actual_day
        focus = focus_on(c, day)
        all_records = actions.facts(c)
        selected_ids = {r['id'] for r in all_records if focus and r.get('focus_day_id') == focus['id']}
        records = [r for r in all_records if r['id'] in selected_ids or r.get('reverses_record_id') in selected_ids]
        from .metrics import aggregate
        from datetime import timedelta
        week = day - timedelta(days=day.weekday())
        progress = aggregate(all_records, start=week, end=day)
        from .metrics import effective
        continuation = max((r for r in effective(all_records) if r['activity_date'] < str(day) and r.get('next_step', '').strip()),
                           key=lambda r: r['activity_at'], default=None)
        return {**state, 'continuation': continuation, 'progress': progress, 'date': str(day), 'timezone': current['timezone'], 'focus': focus,
                'execution': actions.active(c), 'records': records, 'read_only': str(day) != str(actual_day)}
