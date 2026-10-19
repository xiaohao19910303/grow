"""Read-only check-ins projected from tenant-scoped learning completions."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo


def read_checkins(conn):
    tables = {row[0] for row in conn.execute(
        'SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
    result = {'checkins': {}, 'modules': []}

    def completed(module, stamp):
        try:
            moment = datetime.fromisoformat((stamp or '').replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return
        zone = ZoneInfo('Asia/Shanghai')
        day = moment.replace(tzinfo=zone) if moment.tzinfo is None else moment.astimezone(zone)
        result['checkins'].setdefault(day.date().isoformat(), {})[module] = 3

    if 'copilot_learning_records' in tables:
        for row in conn.execute("SELECT module_id,completed_at FROM copilot_learning_records WHERE module_id='renzhi' AND round_id=1"):
            completed(row['module_id'], row['completed_at'])
    if 'study_learning_records' in tables:
        for row in conn.execute('SELECT module_id,completed_at FROM study_learning_records'):
            completed(row['module_id'], row['completed_at'])
    if {'learning_plans', 'learning_feedback'} <= tables:
        plans = {row['id']: json.loads(row['data']) for row in conn.execute('SELECT id,data FROM learning_plans ORDER BY id')}
        result['modules'] = [{'id': pid, 'name': plan['name'], 'color': '#7C5CF0'} for pid, plan in plans.items()]
        for row in conn.execute('SELECT plan_id,data FROM learning_feedback'):
            feedback = json.loads(row['data'])
            if row['plan_id'] in plans and feedback.get('state') == 'completed':
                completed(row['plan_id'], feedback.get('date'))
    return result
