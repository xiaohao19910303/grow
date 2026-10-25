"""Private course-plan tracking; explicit source feedback remains the learning truth."""
import hashlib
import json

from fastapi import Request
import action_plans as actions
from copilot.core import Problem
from plans.store import integer, text


def guard(request):
    origin = f'{request.url.scheme}://{request.url.netloc}'
    if request.headers.get('X-Copilot-Request') != '1' or request.headers.get('Origin', origin) != origin or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        actions.fail(403, '需要同源请求。')
    if request.headers.get('X-Grow-Action-Schema') != '2':
        actions.fail(409, '行动服务合同需升级，请刷新后重试。', 'CONTRACT_UPGRADE_REQUIRED')


def ledger(c, pid):
    row = c.execute('SELECT data FROM learning_action_links WHERE id=?', (pid,)).fetchone()
    return json.loads(row[0]) if row else None


def source(store, pid):
    try:
        return store.plan(pid), store.version(pid)['document'], {l['lesson_no']: l for l in store.lessons(pid)}
    except Problem as exc:
        actions.fail(exc.status, exc.message)


def target(pid, number):
    return actions.StudyTarget(kind='plan', plan_id=pid, lesson_no=number).model_dump()


def available(c):
    row = c.execute('SELECT data FROM action_link_state WHERE id=1').fetchone()
    return not row or json.loads(row[0]).get('phase') not in ('pending', 'active')


def projection(store, pid):
    p, doc, published = source(store, pid)
    with actions.connection() as c:
        saved = ledger(c, pid)
        plans = {r['id']: actions.public(r) for r in c.execute('SELECT * FROM action_plans')}
        management = available(c) and bool(getattr(store, 'remote', False))
    mappings = (saved or {}).get('lessons', {})
    lessons = []
    for lesson in doc['lessons']:
        n = lesson['number']; course = published.get(n); mapping = mappings.get(str(n), {})
        action = plans.get(mapping.get('action_id'))
        changed = bool(mapping) and (not action or action['status'] == 'archived' or action['completion_mode'] != 'content' or action['target'] != target(pid, n))
        lessons.append({'number': n, 'title': lesson['topic'], 'stage': lesson['stage'],
                        'published': course is not None, 'learning_state': (course or {}).get('learning_state', 'unknown'),
                        'action_id': mapping.get('action_id'), 'action_status': (action or {}).get('status'), 'action_changed': changed})
    def counts(rows):
        done = sum(l['published'] and l['learning_state'] == 'completed' for l in rows)
        return {'total_lessons': len(rows), 'published_lessons': sum(l['published'] for l in rows),
                'completed_lessons': done, 'percent': round(done * 100 / len(rows)) if rows else 0}
    return {'id': pid, 'plan_id': pid, 'name': p['name'], 'version': p['version'], 'status': p['status'],
            'linked': saved is not None, 'enabled': bool(saved and saved['enabled']),
            'action_management_available': management, **counts(lessons), 'lessons': lessons,
            'missing_action_count': sum(l['published'] and l['learning_state'] != 'completed' and not l['action_id'] for l in lessons),
            'stages': [{'number': i, 'title': stage['title'], **counts([l for l in lessons if l['stage'] == i])}
                       for i, stage in enumerate(doc['stages'], 1)]}


def link(store, pid, key, expected_version, enabled=True):
    text(key, '请求标识', 160); integer(expected_version, 1, 1000000, '正式版本')
    if type(enabled) is not bool:
        actions.fail(422, '自动补入开关须为布尔值。')
    if not getattr(store, 'remote', False):
        actions.fail(409, '关联行动需要当前 GitHub 与数据库存储。')
    with store.lock():
        p, doc, published = source(store, pid)
        if p['version'] != expected_version:
            actions.fail(409, '正式规划已改版，请刷新后核对。')
        if enabled and p['status'] != 'active':
            actions.fail(409, '请先恢复学习规划，再同步行动。')
        with actions.connection(True) as c:
            def work():
                saved = ledger(c, pid) or {'id': pid, 'lessons': {}, 'linked_at': actions.clock().isoformat()}
                saved['enabled'] = enabled
                candidates = [actions.public(r) for r in c.execute('SELECT * FROM action_plans ORDER BY id')]
                if enabled:
                    for lesson in doc['lessons']:
                        n = lesson['number']; course = published.get(n)
                        if str(n) in saved['lessons'] or not course or course.get('learning_state') == 'completed':
                            continue
                        identity = target(pid, n)
                        old = next((a for a in candidates if a['status'] != 'archived' and a['completion_mode'] == 'content' and a['target'] == identity), None)
                        if old is None:
                            fields = actions.NewPlan(title=f"{p['name']} · 第{n}课 {lesson['topic']}"[:160], period='day',
                                                     completion_mode='content', target=identity, key=key)
                            old = actions.schedule_in_connection(c, fields)['plan']
                        saved['lessons'][str(n)] = {'action_id': old['id']}
                saved['version'] = p['version']
                c.execute('INSERT INTO learning_action_links VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (pid, actions.encoded(saved)))
                return {'plan_id': pid, 'enabled': enabled}
            actions.operation(c, key, {'op': 'learning-plan-link', 'id': pid, 'version': expected_version, 'enabled': enabled}, work)
    return projection(store, pid)


def after_save(store, result, source_key, opt_in=False, request=None):
    """A committed formal publication must never be reported as failed by auxiliary sync."""
    pid = result['plan_id']
    try:
        with store.conn() as c:
            saved = ledger(c, pid)
        if not opt_in and not (saved and saved['enabled']):
            return result
        plan = store.plan(pid)
        if plan['status'] != 'active':
            return result
        if request is not None:
            guard(request)
        sync_key = 'learning-sync-' + hashlib.sha256(f'{source_key}:{pid}:{plan["version"]}'.encode()).hexdigest()
        return {**result, 'learning_actions': link(store, pid, sync_key, plan['version'])}
    except Exception:
        return {**result, 'learning_action_sync_error': '正式内容已保存，关联行动尚未同步。请在规划详情重试同步，无需再次发布。'}


def register(app, router, store, payload):
    @app.get('/api/plan-actions')
    def listing():
        with store.conn() as c:
            ids = [r[0] for r in c.execute('SELECT id FROM learning_action_links ORDER BY id')]
        return {'plans': [projection(store, pid) for pid in ids]}

    @router.get('/{pid}/actions')
    def read(pid: str):
        return projection(store, pid)

    @router.post('/{pid}/actions')
    def write(pid: str, request: Request, body: payload):
        guard(request)
        data = body.data
        return link(store, pid, data.get('key'), data.get('expected_version'), data.get('enabled', True))
