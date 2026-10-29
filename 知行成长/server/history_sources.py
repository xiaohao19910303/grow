"""历史来源公共合同：搜索与 AI 共用身份、业务日期及原记录跳转。"""
from datetime import date, datetime
import json

from copilot.core import digest, encoded

SEARCHABLE_MODULES = {key: {'label': label} for key, label in (
    ('learning', '学习记录'), ('reflection', '日常记录'), ('decision', '决策记录'),
    ('prediction', '预测记录'), ('review', '四问复盘'), ('insight', '灵感记录'),
    ('knowledge', '知识图谱'), ('action', '行动记录'),('investment','投资记录'))}

# Only application-owned table/column names appear in SQL. User inputs are parameters.
SOURCES = (
    ('custom_records', 'learning', ('data',)),
    ('study_learning_records', 'learning', ('module_id', 'filename', 'lesson_no', 'topic', 'summary_text')),
    ('copilot_learning_records', 'learning', ('module_id', 'lesson_no', 'summary_text', 'review_answers')),
    ('course_study_notes', 'learning', ('kind', 'course_id', 'data')),
    ('learning_feedback', 'learning', ('plan_id', 'lesson_no', 'data')),
    ('reading_records', 'learning', ('data',)),
    ('cloud_documents', 'learning', ('path', 'data')),
    ('reflection_entries', 'reflection', ('data',)),
    ('decisions', 'decision', ('title', 'context', 'options', 'reason', 'expected', 'actual')),
    ('predictions', 'prediction', ('statement', 'result', 'deviation')),
    ('reviews', 'review', ('thought', 'actual', 'gap', 'action')),
    ('insights', 'insight', ('insight', 'source')),
    ('knowledge', 'knowledge', ('name', 'category', 'summary', 'source')),
    ('action_plans', 'action', ('data',)),
    ('action_executions', 'action', ('data',)),
    ('investment_discovery','investment',('data',)),
)


def text(value):
    if isinstance(value, dict):
        return ' · '.join(text(v) for v in value.values() if v)
    if isinstance(value, list):
        return ' · '.join(text(v) for v in value if v)
    return str(value) if value is not None else ''


def record_day(value):
    """Business dates and completion timestamps use the application's China day."""
    if not value:
        return ''
    value = str(value)
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        from zoneinfo import ZoneInfo
        timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if timestamp.tzinfo:
            timestamp = timestamp.astimezone(ZoneInfo('Asia/Shanghai'))
        return timestamp.date().isoformat()
    except ValueError:
        return ''


def normalize(source, module, row):
    data = row['data'] if source in {table for table, _, fields in SOURCES if 'data' in fields} else None
    if isinstance(data, str):
        data = json.loads(data)
    item = {**row, **(data if isinstance(data, dict) else {})}
    if item.get('archived_at') or item.get('archived'):
        return None
    identity = row.get('id')
    title = item.get('title') or item.get('name') or item.get('statement') or item.get('thought') or item.get('insight')
    body = ''
    day = item.get('date') or item.get('record_date') or item.get('completed_at') or item.get('updated_at') or item.get('saved_at') or item.get('created_at')
    target = {'kind': 'legacy', 'module': module, 'id': identity}
    if source == 'study_learning_records':
        identity = item['module_id'] + '/' + item['filename']
        title, body = item['topic'], item.get('summary_text')
        target = {'kind': 'study', 'module': item['module_id'], 'course': item['filename']}
    elif source == 'copilot_learning_records':
        identity = f"{item['module_id']}/{item['round_id']}/{item['lesson_no']}"
        title = f"认知课程 · 第 {item['lesson_no']} 课"
        body = text([item.get('summary_text'), item.get('review_answers')])
        target = {'kind': 'copilot', 'lesson_no': item['lesson_no']}
    elif source in ('course_study_notes', 'learning_feedback'):
        kind = item.get('kind', 'plan')
        course = item.get('course_id') or f"{item['plan_id']}/{item['lesson_no']}"
        identity = kind + '/' + course
        title = f"{'课程笔记' if source == 'course_study_notes' else '学习反馈'} · {course}"
        body = text([item.get('notes'), item.get('answers'), item.get('comment')])
        target = {'kind': 'study', 'module': kind, 'course': course}
    elif source == 'reflection_entries':
        title = item.get('prompt_kind') or '日常记录'
        body = text([item.get('raw_text'), item.get('guided_answers'), item.get('adopted_summary'), item.get('tags')])
        target = {'kind': 'reflection', 'id': identity}
    elif source == 'reading_records':
        if item.get('type') != 'article':
            return None
        title = item.get('zh_title') or title
        body = text([item.get(k) for k in ('summary', 'guide', 'full_content', 'feedback', 'note')])
        target = {'kind': 'article', 'id': identity}
    elif source == 'cloud_documents':
        path = row['path']
        if not path.startswith('认知阅读/阅读笔记/') or not path.endswith('.md'):
            return None
        identity = path
        title = '阅读笔记 · ' + path.rsplit('/', 1)[-1][:-3]
        body = item.get('text', '')
        target = {'kind': 'article', 'id': path.rsplit('/', 1)[-1][:-3]}
    elif source == 'action_plans':
        day = item.get('start_date')
        body = text([item.get('target'), item.get('note'), item.get('status')])
        target = {'kind': 'action', 'id': identity}
    elif source == 'investment_discovery':
        body=item.get('summary','私有投资记录')
        target={'kind':'investment','id':identity,'resource':item['record_kind'],'account_id':item['account_id']}
    elif source == 'action_executions':
        day = item.get('business_date') or item.get('started_at')
        title = item.get('title') or '行动执行记录'
        body = text([item.get('note'), item.get('outcome'), item.get('actual_minutes')])
        target = {'kind': 'action', 'id': row['plan_id'], 'execution_id': identity}
    else:
        fields = next(fields for table, _, fields in SOURCES if table == source)
        body = text([item.get(k) for k in fields if k != 'data'])
        if source == 'custom_records':
            body = text(data)
    title = text(title) or f"{SEARCHABLE_MODULES[module]['label']} {identity}"
    body = text(body)
    return {'id': identity, 'source': source, 'module': module,
            'module_label': SEARCHABLE_MODULES[module]['label'], 'title': title[:200],
            'summary': body[:300], 'content': body[:300], 'date': row.get('_discovery_date', record_day(day)),
            'target': target}


# 历史原记录只按服务端登记的身份读取，不接受客户端传入表名、列名或路径。
RECORD_SOURCES = {
    **{table: ('id',) for table in ('reflection_entries', 'decisions', 'predictions', 'reviews',
        'insights', 'knowledge', 'action_plans', 'action_executions', 'action_reviews', 'reading_records',
        'learning_plans', 'investment_objects', 'behavior_applications', 'error_records')},
    'course_study_notes': ('kind', 'course_id'),
    'copilot_learning_records': ('module_id', 'round_id', 'lesson_no'),
    'copilot_feedback': ('module_id', 'round_id', 'lesson_no'),
    'study_learning_records': ('module_id', 'filename'),
    'learning_feedback': ('plan_id', 'lesson_no'),
    'learning_lessons': ('plan_id', 'lesson_no'),
    'cloud_documents': ('path',),
    'learning_drafts': ('id',),
    'learning_plan_versions': ('plan_id', 'version'),
}


def record_hash(row, fields=None):
    value = dict(row)
    if fields:
        data = value.get('data')
        if isinstance(data, str): data = json.loads(data)
        if isinstance(data, dict): value = {**value, **data}
        projected = []
        for path in fields:
            current = value
            for part in (path if isinstance(path, list) else [path]):
                current = current.get(part) if isinstance(current, dict) else None
            projected.append(current)
        value = projected
    return digest(encoded(value))


def record_source(c, kind, keys, label, sent, *, target=None, scope='本次选定字段', truncated=False, fields=None):
    from ai_evidence import source
    columns = RECORD_SOURCES[kind]
    if len(keys) != len(columns): raise ValueError('Invalid source identity')
    row = c.execute('SELECT * FROM ' + kind + ' WHERE ' + ' AND '.join(k + '=?' for k in columns), tuple(keys)).fetchone()
    origin = {'kind': kind, 'keys': list(keys), 'fields': fields, 'hash': record_hash(row, fields) if row else None}
    normalized = None
    if row:
        module = next((module for table, module, _ in SOURCES if table == kind), None)
        if module:normalized = normalize(kind, module, dict(row))
    if target is None and normalized:target = normalized['target']
    if target is None and kind == 'copilot_feedback':target = {'kind':'copilot','lesson_no':keys[2]}
    if target is None and kind in ('learning_plans','learning_plan_versions'):target = {'kind':'plan','id':keys[0]}
    value = source(kind, normalized['id'] if normalized else encoded(list(keys)), label, sent,
                   target=target, scope=scope, truncated=truncated, origin=origin,
                   date=normalized['date'] if normalized else None)
    value['version'] = origin['hash']
    return value


def teaching_source(kind, keys, label, sent, version, *, target=None, scope='本次选定教学资料', truncated=False):
    """教学来源只接受应用登记的解析器，身份与版本之外不补入原文。"""
    from ai_evidence import source
    return source(kind, encoded(keys), label, sent, target=target, version=version, scope=scope,
        truncated=truncated, origin={'kind':'teaching-record','source':kind,'keys':keys,'version':version})


def availability(c, item, cache=None, resolvers=None):
    origin = item.get('origin')
    if not origin: return 'captured_input'
    kind = origin.get('kind')
    if kind == 'teaching-record':
        resolver = (resolvers or {}).get(origin.get('source'))
        if resolver is None:return 'unverifiable'
        cache = cache if cache is not None else {}
        key = ('teaching', origin['source'], encoded(origin['keys']))
        try:
            if key not in cache:cache[key] = resolver(*origin['keys'])
            return 'unchanged' if cache[key] == origin['version'] else 'changed'
        except Exception as error:
            return 'deleted' if getattr(error, 'status', getattr(error, 'status_code', None)) == 404 else 'unavailable'
    if kind == 'behavior-summary':
        from datetime import date
        from behavior_report.analyzer import collect_data_summary
        cache = cache if cache is not None else {}
        key = (origin['period_days'], origin['business_day'])
        c.execute('SAVEPOINT evidence_aggregate')
        try:
            if key not in cache:
                cache[key] = collect_data_summary(None, key[0], connection=c, end_day=date.fromisoformat(key[1]))
            state = 'unchanged' if digest(encoded(cache[key][origin['field']])) == item['content_hash'] else 'changed'
            c.execute('RELEASE SAVEPOINT evidence_aggregate')
            return state
        except Exception:
            c.execute('ROLLBACK TO SAVEPOINT evidence_aggregate');c.execute('RELEASE SAVEPOINT evidence_aggregate')
            return 'unavailable'
    columns = RECORD_SOURCES.get(kind)
    if not columns or len(origin.get('keys', [])) != len(columns): return 'unverifiable'
    c.execute('SAVEPOINT evidence_source')
    try:
        row = c.execute('SELECT * FROM ' + kind + ' WHERE ' + ' AND '.join(k + '=?' for k in columns), tuple(origin['keys'])).fetchone()
        state = 'deleted'
        if row is not None:
            value=dict(row);data=value.get('data')
            if isinstance(data,str):data=json.loads(data)
            if isinstance(data,dict):value.update(data)
            archived=value.get('archived') in (True,1,'true','1') or bool(value.get('archived_at')) or value.get('status')=='archived'
            state='archived' if archived else 'unchanged' if record_hash(row, origin.get('fields')) == origin['hash'] else 'changed'
        c.execute('RELEASE SAVEPOINT evidence_source')
        return state
    except Exception:
        c.execute('ROLLBACK TO SAVEPOINT evidence_source')
        c.execute('RELEASE SAVEPOINT evidence_source')
        return 'unavailable'
