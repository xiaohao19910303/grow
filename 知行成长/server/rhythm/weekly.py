"""Cross-action weekly projection and explicitly confirmed revision snapshots."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
import uuid
import action_plans as actions
from . import service
from .contracts import activity_date
from .metrics import aggregate


def view(c, week):
    week = date.fromisoformat(str(week))
    if week.weekday() != 0:
        actions.fail(422, '请选择周一作为周起始日期。')
    prefs = service.preferences(c)['preferences']
    today = activity_date(actions.clock(), prefs['timezone'])
    if week > today:
        actions.fail(422, '未来周尚无回顾。')
    end = week + timedelta(days=6)
    # Freeze past weekly settings using the configuration effective at that time.
    boundary = datetime.combine(end + timedelta(days=1), time.min, ZoneInfo(prefs['timezone'])) - timedelta(microseconds=1)
    prefs = service.preferences(c, min(boundary, actions.clock()))['preferences']
    all_records = actions.facts(c)
    stats = aggregate(all_records, start=week, end=min(end, today))
    records = [r for r in all_records if r['id'] in set(stats['source_fact_ids'])]
    records.sort(key=lambda r: (r['activity_at'], r['id']), reverse=True)
    payload = dict(stats=stats, records=records, timezone=prefs['timezone'], target_days=prefs['weekly_target_days'])
    digest = hashlib.sha256(actions.encoded(payload).encode()).hexdigest()
    row = c.execute('SELECT data FROM action_weekly_cards WHERE week_start=?', (str(week),)).fetchone()
    card = json.loads(row[0]) if row else None
    return dict(week_start=str(week), week_end=str(end), as_of=str(min(today, end)), is_partial=today <= end,
                **payload, snapshot_hash=digest, card=card, changed=bool(card and card['snapshot_hash'] != digest))


def confirm(week, body):
    with actions.connection(True) as c:
        service.bootstrap(c)
        def work():
            service.require_enabled(c)
            current = view(c, week); old = current['card']
            if (old['revision'] if old else 0) != body.expected_revision:
                actions.fail(409, '周卡已更新，请保留输入并刷新。', 'REVISION_CONFLICT')
            if current['snapshot_hash'] != body.snapshot_hash:
                actions.fail(409, '本周事实已有变化，请重看后确认。', 'SNAPSHOT_CONFLICT')
            if not set(body.selected_execution_ids) <= set(current['stats']['source_fact_ids']):
                actions.fail(422, '请选择本周有效的执行成果。')
            if body.adjustment_target_plan_id:
                plan = actions.get(c, body.adjustment_target_plan_id)
                today = activity_date(actions.clock(), service.preferences(c)['preferences']['timezone'])
                if plan['period'] != 'day' or plan['status'] != 'active' or not plan.get('start_date') or plan['start_date'] < str(today):
                    actions.fail(422, '调整只能关联今天或未来可执行的日行动。')
                ancestor = plan
                while ancestor.get('parent_id'):
                    ancestor = actions.get(c, ancestor['parent_id'])
                    if ancestor['status'] != 'active':
                        actions.fail(409, '请先恢复上级计划。')
            card = {k: v for k, v in current.items() if k not in ('card', 'changed')}
            card.update(id=old['id'] if old else 'weekly-' + uuid.uuid4().hex,
                        revision=body.expected_revision + 1, selected_execution_ids=body.selected_execution_ids,
                        adjustment_text=body.adjustment_text, adjustment_target_plan_id=body.adjustment_target_plan_id,
                        confirmed_at=actions.clock().isoformat(), history=[*old.get('history', []),
                        {k: v for k, v in old.items() if k != 'history'}] if old else [])
            c.execute('''INSERT INTO action_weekly_cards VALUES (?,?,?,?)
                ON CONFLICT(week_start) DO UPDATE SET data=EXCLUDED.data,revision=EXCLUDED.revision''',
                (card['id'], str(week), actions.encoded(card), card['revision']))
            from .events import emit
            emit(c, 'weekly_card_confirmed', 'weekly:' + card['id'] + ':' + str(card['revision']), week_start=str(week), revision=card['revision'])
            if body.adjustment_target_plan_id:
                emit(c, 'adjustment_linked', 'adjust:' + card['id'] + ':' + str(card['revision']), week_start=str(week), plan_id=body.adjustment_target_plan_id)
            return {'card': card}
        return actions.operation(c, body.key, {'op': 'rhythm.weekly', 'week_start': str(week), **body.model_dump(mode='json')}, work)
