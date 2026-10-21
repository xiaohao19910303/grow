"""Shared report facts, projected from the same completions as learning history.

A module can complete once per local day. The three duration sources describe
potentially overlapping activity, so they are reported separately, never summed.
"""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from learning_checkins import read_checkins

SHANGHAI = ZoneInfo('Asia/Shanghai')


def shanghai_today():
    return datetime.now(SHANGHAI).date()


def _local_day(value):
    try:
        moment = datetime.fromisoformat((value or '').replace('Z', '+00:00'))
        return (moment.replace(tzinfo=SHANGHAI) if moment.tzinfo is None
                else moment.astimezone(SHANGHAI)).date().isoformat()
    except (ValueError, TypeError):
        return None


def collect_activity(conn, start=None, end=None, *, today=None):
    """Read tenant-scoped completion/activity facts, optionally for a date range.

    ``total_minutes`` retains the legacy manually recorded habits contract.
    ``total_days`` counts learning days; ``active_days`` also includes habit notes
    or positive manually recorded minutes. Streak always spans all history up to
    today, independently of the report window.
    """
    today = today or shanghai_today()
    end = end or today.isoformat()

    def in_period(day):
        return day is not None and (start is None or start <= day) and day <= end

    automatic = read_checkins(conn)
    merged = {day: dict(modules) for day, modules in automatic['checkins'].items()}
    for row in conn.execute('SELECT date,module_id,level FROM checkins WHERE level>0'):
        if _local_day(row['date']):
            day = _local_day(row['date'])
            merged.setdefault(day, {})[row['module_id']] = max(
                merged.get(day, {}).get(row['module_id'], 0), row['level'])

    active = set(merged)
    manual_minutes = 0
    habit_rows = 0
    for row in conn.execute('SELECT date,minutes,note FROM habits'):
        day = _local_day(row['date'])
        if not day:
            continue
        if (row['minutes'] or 0) > 0 or (row['note'] or '').strip():
            active.add(day)
        if in_period(day):
            manual_minutes += row['minutes'] or 0
            habit_rows += 1

    checkins = {day: modules for day, modules in merged.items() if in_period(day)}
    module_stats = {}
    for modules in checkins.values():
        for module in modules:
            module_stats[module] = module_stats.get(module, 0) + 1

    current = today
    if current.isoformat() not in active:
        current -= timedelta(days=1)
    streak = 0
    while current.isoformat() in active:
        streak += 1
        current -= timedelta(days=1)

    tables = {row[0] for row in conn.execute(
        'SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
    course_seconds = 0
    for table, condition in (('copilot_learning_records', " WHERE module_id='renzhi' AND round_id=1"),
                             ('study_learning_records', '')):
        if table in tables:
            for row in conn.execute(f'SELECT completed_at,time_spent_seconds FROM {table}{condition}'):
                if in_period(_local_day(row['completed_at'])):
                    course_seconds += max(0, row['time_spent_seconds'] or 0)

    action_minutes = 0
    if 'action_executions' in tables:
        for row in conn.execute("SELECT data FROM action_executions WHERE state<>'running'"):
            execution = json.loads(row['data'])
            if in_period(_local_day(execution.get('business_date'))):
                action_minutes += max(0, execution.get('actual_minutes', 0) or 0)

    return {
        'checkins': checkins,
        'modules': automatic['modules'],
        'module_stats': module_stats,
        'total_days': len(checkins),
        'active_days': sum(in_period(day) for day in active),
        'total_minutes': manual_minutes,
        'avg_habit_minutes': round(manual_minutes / habit_rows) if habit_rows else 0,
        'streak': streak,
        'duration_sources': {
            'manual_habit_minutes': manual_minutes,
            'course_learning_seconds': course_seconds,
            'action_confirmed_minutes': action_minutes,
            'total_minutes_source': 'manual_habits',
            'note': '手工补记分钟、课程记录秒数与行动本人确认分钟分别展示；可能重叠，不相加。课程完成或计时进行中不推算行动投入。',
        },
    }


def count_reflections(conn, start, end):
    """Count active daily entries (free or guided) plus retained legacy reviews.

    Entries are counted once by their current identity and business record date;
    editing/AI versions do not create extra reflections. Optional feature tables
    may not have been initialized for a tenant yet.
    """
    tables = {row[0] for row in conn.execute(
        'SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
    total = 0
    if 'reviews' in tables:
        total += conn.execute('SELECT COUNT(*) FROM reviews WHERE date>=? AND date<=?',
                              (start, end)).fetchone()[0]
    if 'reflection_entries' in tables:
        total += conn.execute("""SELECT COUNT(*) FROM reflection_entries
            WHERE data::jsonb->>'record_date'>=? AND data::jsonb->>'record_date'<=?
              AND COALESCE(data::jsonb->>'archived_at','')=''
              AND COALESCE(data::jsonb->>'archived','false') NOT IN ('true','1')""",
                              (start, end)).fetchone()[0]
    return total
