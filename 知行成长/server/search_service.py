"""Tenant-scoped discovery of saved records, shared by search and timeline."""
from datetime import date, datetime
import json
import heapq
import itertools
import uuid
from contextlib import contextmanager
from psycopg2.extras import RealDictCursor
import logging
import os
from pathlib import Path
import re
from typing import Optional

import db

log = logging.getLogger(__name__)
SEARCHABLE_MODULES = {key: {'label': label} for key, label in (
    ('learning', '学习记录'), ('reflection', '日常记录'), ('decision', '决策记录'),
    ('prediction', '预测记录'), ('review', '四问复盘'), ('insight', '灵感记录'),
    ('knowledge', '知识图谱'), ('action', '行动记录'))}

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


# Raw columns stay inside PostgreSQL; only bounded display excerpts cross the wire.
JSON_PREVIEWS = {
    'course_study_notes': ('notes', 'answers'),
    'learning_feedback': ('comment',),
    'reading_records': ('type', 'title', 'zh_title', 'summary', 'guide', 'full_content', 'feedback', 'note'),
    'cloud_documents': ('text',),
    'reflection_entries': ('prompt_kind', 'raw_text', 'guided_answers', 'adopted_summary', 'tags'),
    'action_plans': ('title', 'target', 'note', 'status'),
    'action_executions': ('title', 'note', 'outcome', 'actual_minutes'),
}
JSON_DATE_KEYS = ('date', 'record_date', 'completed_at', 'updated_at', 'saved_at', 'created_at')


@contextmanager
def streaming_rows(conn, sql, params=()):
    """A server-side cursor bounds network buffers even for long local-note scans."""
    with conn._conn.cursor(name='discovery_' + uuid.uuid4().hex, cursor_factory=RealDictCursor) as cursor:
        cursor.itersize = 64
        cursor.execute(sql, tuple(params))
        yield cursor


def source_query(source, fields, query, start_date, end_date):
    columns = set(fields) - {'data'}
    has_json = 'data' in fields
    identity = 'id::text'
    prefilter = None
    if source == 'study_learning_records':
        columns.update(('module_id', 'filename', 'lesson_no', 'completed_at'))
        identity = "module_id || '/' || filename"
        raw_day = 'completed_at'
    elif source == 'copilot_learning_records':
        columns.update(('module_id', 'round_id', 'lesson_no', 'completed_at', 'archived'))
        identity = "module_id || '/' || round_id::text || '/' || lesson_no::text"
        raw_day = 'completed_at'
    elif source == 'course_study_notes':
        columns.add('updated_at')
        identity = "kind || '/' || course_id"
        raw_day = 'updated_at'
    elif source == 'learning_feedback':
        identity = "'plan/' || plan_id || '/' || lesson_no::text"
        raw_day = "doc->>'date'"
    elif source == 'cloud_documents':
        identity = 'path'
        raw_day = "doc->>'updated_at'"
        prefilter = "starts_with(path,'认知阅读/阅读笔记/') AND right(path,3)='.md'"
    elif source == 'action_plans':
        columns.add('id')
        raw_day = "doc->>'start_date'"
    elif source == 'action_executions':
        columns.update(('id', 'plan_id'))
        raw_day = "COALESCE(NULLIF(doc->>'business_date',''),doc->>'started_at')"
    elif has_json:
        columns.add('id')
        raw_day = 'COALESCE(' + ','.join("NULLIF(doc->>'" + key + "','')" for key in JSON_DATE_KEYS) + ")"
        if source == 'reading_records':
            prefilter = "starts_with(id,'article-')"
    else:
        columns.update(('id', 'date'))
        raw_day = 'date'
    raw_columns = sorted(columns)
    base_projection = raw_columns[:]
    if has_json:
        document = "replace(data,chr(92)||'u0000',chr(92)||'ufffd')::jsonb"
        # A guarded expression prevents the planner from parsing unrelated bodies
        # before the path/type predicate, without materializing the entire table.
        if prefilter:
            document = f"CASE WHEN {prefilter} THEN {document} ELSE '{{}}'::jsonb END"
        base_projection.append(document + ' AS doc')
    prefix = 'WITH source_rows AS (SELECT ' + ','.join(base_projection) + ' FROM ' + source
    if prefilter:
        prefix += ' WHERE ' + prefilter
    # Keep each JSON parse in a streaming projection. OFFSET 0 prevents the
    # planner from expanding it into every date/preview expression, without
    # materializing all document bodies in a CTE or transferring them to Python.
    if has_json:
        prefix += ' OFFSET 0'
    prefix += ') '
    day = (f"CASE WHEN length({raw_day})=10 THEN {raw_day} "
           f"WHEN {raw_day} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}[T ]' THEN "
           f"CASE WHEN {raw_day} ~ '(Z|[+-][0-9]{{2}}:[0-9]{{2}}|[+-][0-9]{{4}})$' "
           f"THEN to_char(({raw_day})::timestamptz AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD') "
           f"ELSE left({raw_day},10) END ELSE '' END")
    if not has_json and source not in ('study_learning_records', 'copilot_learning_records'):
        day = "COALESCE(date,'')"
    conditions, params = [], []
    if has_json:
        conditions.extend(("COALESCE(doc->>'archived','false') NOT IN ('true','1')", "COALESCE(doc->>'archived_at','')=''"))
    if source == 'copilot_learning_records':
        conditions.append('COALESCE(archived,0)=0')
    if source == 'reading_records':
        conditions.append("doc->>'type'='article'")
    if query:
        expressions = ['doc::text' if field == 'data' else f'{field}::text' for field in fields]
        conditions.append("strpos(lower(concat_ws(' '," + ','.join(expressions) + ')),lower(%s))>0')
        params.append(query)
    if start_date:
        conditions.append(f'({day}) >= %s')
        params.append(start_date)
    if end_date:
        conditions.append(f'({day}) <= %s')
        params.append(end_date)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    excluded = {'date', 'completed_at', 'updated_at', 'archived'}
    projection = [column if column in {'id','kind','course_id','module_id','filename','lesson_no','round_id','path','plan_id'}
                  else f'left({column}::text,300) AS {column}' for column in raw_columns if column not in excluded]
    if source == 'custom_records':
        projection.append("jsonb_build_object('title',COALESCE(doc->>'title',doc->>'name',doc->>'headline'),'note',left(doc::text,300)) AS data")
    elif has_json:
        previews = JSON_PREVIEWS[source]
        projection.append('jsonb_build_object(' + ','.join("'" + key + "',left(doc->>'" + key + "',300)" for key in previews) + ') AS data')
    projection.extend((day + ' AS _discovery_date', identity + ' AS _identity'))
    return prefix, where, params, ','.join(projection), day


def local_reading_notes(conn, query, start_date, end_date, include_body=True):
    """Only local files need scanning; filter their mtime before reading a body."""
    if os.getenv('PLAN_CONTENT_BACKEND') == 'github':
        return
    from tenancy import learning_root
    root = learning_root(Path(os.getenv('LEARN_ROOT', Path(__file__).resolve().parents[1] / '学习资料')))
    if not (root / '认知阅读' / '阅读笔记').is_dir():
        return
    if conn.execute("SELECT to_regclass('reading_records')").fetchone()[0] is None:
        return
    sql = """SELECT id,replace(data,chr(92)||'u0000',chr(92)||'ufffd')::jsonb->>'title' AS title
        FROM reading_records WHERE starts_with(id,'article-')
        AND replace(data,chr(92)||'u0000',chr(92)||'ufffd')::jsonb->>'type'='article'
        AND COALESCE(replace(data,chr(92)||'u0000',chr(92)||'ufffd')::jsonb->>'archived','false') NOT IN ('true','1')"""
    with streaming_rows(conn, sql) as rows:
        for row in rows:
            aid = row['id']
            if not re.fullmatch(r'article-[A-Za-z0-9_-]+', aid):
                continue
            path = root / '认知阅读' / '阅读笔记' / (aid + '.md')
            if not path.is_file():
                continue
            for part in (path, *path.parents):
                if part.is_symlink():
                    raise ValueError('Reading note path cannot contain symbolic links')
                if part == root:
                    break
            day = record_day(datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat())
            if (start_date and day < start_date) or (end_date and day > end_date):
                continue
            body = path.read_text(encoding='utf-8') if query or include_body else ''
            if query and query.casefold() not in body.casefold():
                continue
            yield {'id': aid, 'source': 'reading_notes', 'module': 'learning',
                   'module_label': '学习记录', 'title': '阅读笔记 · ' + (row['title'] or aid),
                   'summary': body[:300], 'content': body[:300], 'date': day,
                   'target': {'kind': 'article', 'id': aid}}


def collect_records(modules=None, query=None, start_date=None, end_date=None, page=1, page_size=20, stats_only=False):
    """Exact SQL counts plus a bounded merge of source candidates; no full-body scan in Python."""
    selected = set(modules or SEARCHABLE_MODULES)
    warnings, heap, active_days = [], [], set()
    counts = {module: 0 for module in SEARCHABLE_MODULES}
    limit, serial = page * page_size, itertools.count()
    conn = db.connect()
    def add(record, destination=heap):
        key = (record['date'], record['source'], str(record['id']))
        entry = (key, next(serial), record)
        if len(destination) < limit:
            heapq.heappush(destination, entry)
        elif key > destination[0][0]:
            heapq.heapreplace(destination, entry)
    try:
        for source, module, fields in SOURCES:
            if module not in selected:
                continue
            conn.execute('SAVEPOINT discovery_source')
            try:
                if conn.execute('SELECT to_regclass(%s)', (source,)).fetchone()[0] is None:
                    conn.execute('RELEASE SAVEPOINT discovery_source')
                    continue
                prefix, where, params, projection, day = source_query(source, fields, query, start_date, end_date)
                candidates, days = [], set()
                if stats_only:
                    count = 0
                    days = set()
                    with streaming_rows(conn, prefix + f'SELECT {day} AS day,count(*) AS count FROM source_rows' + where + ' GROUP BY day', params) as rows:
                        for row in rows:
                            count += row['count']
                            if row['day']:
                                days.add(row['day'])
                else:
                    count = conn.execute(prefix + 'SELECT count(*) FROM source_rows' + where, params).fetchone()[0]
                    sql = prefix + 'SELECT ' + projection + ' FROM source_rows' + where + ' ORDER BY _discovery_date DESC,_identity DESC LIMIT %s'
                    with streaming_rows(conn, sql, [*params, limit]) as rows:
                        for row in rows:
                            record = normalize(source, module, dict(row))
                            if record:
                                candidates.append(record)
                conn.execute('RELEASE SAVEPOINT discovery_source')
                counts[module] += count
                active_days.update(days)
                for record in candidates:
                    add(record)
            except Exception as exc:
                conn.execute('ROLLBACK TO SAVEPOINT discovery_source')
                conn.execute('RELEASE SAVEPOINT discovery_source')
                heap[:] = [entry for entry in heap if entry[2]['source'] != source]
                heapq.heapify(heap)
                log.warning('Discovery source unavailable: %s (%s)', source, type(exc).__name__)
                warnings.append({'source': source, 'module': module, 'message': f"{SEARCHABLE_MODULES[module]['label']}的部分内容暂时无法读取，请重试。"})
        if 'learning' in selected:
            conn.execute('SAVEPOINT discovery_notes')
            try:
                note_count, days, note_candidates = 0, set(), []
                for record in local_reading_notes(conn, query, start_date, end_date, include_body=not stats_only):
                    note_count += 1
                    days.add(record['date'])
                    if not stats_only:
                        add(record, note_candidates)
                conn.execute('RELEASE SAVEPOINT discovery_notes')
                counts['learning'] += note_count
                active_days.update(days)
                for entry in note_candidates:
                    add(entry[2])
            except Exception as exc:
                conn.execute('ROLLBACK TO SAVEPOINT discovery_notes')
                conn.execute('RELEASE SAVEPOINT discovery_notes')
                heap[:] = [entry for entry in heap if entry[2]['source'] != 'reading_notes']
                heapq.heapify(heap)
                log.warning('Local reading notes unavailable (%s)', type(exc).__name__)
                warnings.append({'source': 'reading_notes', 'module': 'learning', 'message': '部分阅读笔记暂时无法读取，请重试。'})
        records = [entry[2] for entry in sorted(heap, reverse=True)]
        return {'records': records[(page - 1) * page_size:page * page_size], 'total_count': sum(counts.values()),
                'counts': counts, 'active_days': len(active_days), 'warnings': warnings}
    finally:
        conn.close()


class SearchService:
    def __init__(self, db_path):
        self.db_path = db_path

    def search(self, query: str, module_types: Optional[list[str]] = None,
               start_date=None, end_date=None, page=1, page_size=20):
        result = collect_records(module_types, query.strip(), start_date, end_date, page, page_size) if query and query.strip() else {'records': [], 'total_count': 0, 'warnings': []}
        return {'results': result['records'], 'total_count': result['total_count'],
                'page': page, 'page_size': page_size, 'partial': bool(result['warnings']), 'warnings': result['warnings']}

    def get_search_stats(self):
        result = collect_records(stats_only=True)
        return {module: {'label': config['label'], 'count': result['counts'][module],
                         'partial': any(w['module'] == module for w in result['warnings'])}
                for module, config in SEARCHABLE_MODULES.items()}
