"""AI 分析依据：账号内不可变输入快照、任务/结果引用与只读追溯接口。

业务模块在调用模型前冻结消息，只从快照读取消息；凭证始终由调用方单独传递。
连接由既有账号业务存储提供，公开接口必须具有可信 current_user，不回退 public。
"""
from contextlib import contextmanager
import json
import sqlite3
import uuid

import db
from copilot.core import digest, encoded, fail, now

KINDS = {'behavior-report', 'behavior-result', 'course-background', 'course-summary',
         'copilot', 'study', 'plans', 'plan-draft', 'continuations', 'reflection',
         'reflection-result', 'action-review', 'reading', 'reading-result', 'investments',
         'study-course', 'plan-course', 'plan-result', 'copilot-course'}
LEGACY = '此历史结果未记录完整证据快照。'
TABLES = '''CREATE TABLE ai_evidence_snapshots (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE ai_evidence_links (
    kind TEXT NOT NULL, resource_id TEXT NOT NULL, stage TEXT NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES ai_evidence_snapshots(id),
    PRIMARY KEY(kind,resource_id,stage));
CREATE INDEX ai_evidence_snapshot_links ON ai_evidence_links(snapshot_id);'''


def initialize(c):
    """证据迁移与版本标记同事务；不修复或覆盖未知版本的数据表。"""
    local = isinstance(c, sqlite3.Connection)
    if not local:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':ai-evidence-schema',0))")
    c.execute('CREATE TABLE IF NOT EXISTS ai_evidence_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
    versions = [r[0] for r in c.execute('SELECT version FROM ai_evidence_migrations')]
    if any(v > 1 for v in versions):
        fail('evidence_version', '分析依据版本较新，请升级服务；原数据保留。', 409)
    if 1 not in versions:
        if exists(c, 'ai_evidence_snapshots') or exists(c, 'ai_evidence_links'):
            fail('evidence_schema', '分析依据表缺少迁移标记，请核对；原数据保留。', 503)
        for statement in TABLES.split(';'):
            if statement.strip(): c.execute(statement)
        c.execute('INSERT INTO ai_evidence_migrations VALUES (1,?)', (now(),))
    if not all(exists(c, table) for table in ('ai_evidence_snapshots', 'ai_evidence_links')):
        fail('evidence_schema', '分析依据表不完整，请核对；未清空或重建。', 503)


def exists(c, table):
    if isinstance(c, sqlite3.Connection):
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
    return c.execute('SELECT to_regclass(?)', (table,)).fetchone()[0] is not None


@contextmanager
def connection():
    from tenancy import current_user
    if not current_user.get(): fail('unauthorized', '请先登录。', 401)
    with db.connect() as c: yield c


def source(kind, identity, label, value, *, target=None, version=None, date=None,
           scope='本次选定发送内容', truncated=False, origin=None):
    return {'kind': kind, 'id': str(identity), 'label': label, 'business_date': date,
            'version': version, 'content_hash': digest(encoded(value)), 'scope': scope,
            'truncated': bool(truncated), 'target': target, 'origin': origin}


def inputs(payload, label='本次确认发送的资料'):
    """描述已限定的输入，不扫描或扩大来源；无持久身份的输入不伪称可核验原记录。"""
    values = payload.items() if isinstance(payload, dict) else [('input', payload)]
    names={'input':'输入','text':'正文','answers':'回答','summary':'选定总结','self_ratings':'本人自评','needs_review':'待复习主题',
        'next_directions':'后续方向','lessons':'已完成课程','brief':'学习条件','plan_id':'规划身份','base_version':'规划版本',
        'previous_plan':'原规划','frozen_lessons':'已发布课次','selected_feedback':'选定反馈','parent':'调整基线','parent_hash':'基线版本',
        'scope':'调整范围','instruction':'本次调整要求','course_context':'原备课内容','source_entries':'选定参考资料','source_hash':'资料版本',
        'previous_topics':'最近三课主题','lesson':'本课教学目标','module_id':'模块身份','module_name':'模块名称','lesson_no':'课号',
        'stage':'教学阶段','position_in_stage':'阶段内位置','request':'本次补充要求','form':'本人确认方向','plan':'选定计划',
        'records':'选定行动记录','stats':'统计摘要','start_date':'统计起日','end_date':'统计止日','records_truncated':'行动记录截取说明','reviews':'选定复盘'}
    return [source('submitted', key, label + ' · ' + names.get(str(key), str(key)), value) for key, value in values]


def freeze(c, kind, resource_id, messages, model, *, sources=(), prompt_version='v1',
           stage='input', parent_id=None, selection=None):
    if kind not in KINDS: raise ValueError('Unknown evidence resource')
    initialize(c)
    # JSON round trip freezes nested objects as well as the messages actually sent.
    messages = json.loads(encoded(messages))
    if not isinstance(messages, list) or not messages or any(
            not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant')
            or not isinstance(m.get('content'), str) for m in messages):
        raise ValueError('Invalid evidence messages')
    raw = encoded(messages)
    if len(raw.encode()) > 4_000_000: fail('evidence_size', '本次发送内容过大，请减少资料。', 422)
    row = c.execute('SELECT snapshot_id FROM ai_evidence_links WHERE kind=? AND resource_id=? AND stage=?',
                    (kind, str(resource_id), stage)).fetchone()
    if row:
        old = read(c, row[0])
        if old['input_hash'] != digest(raw) or old['model'] != model:
            fail('evidence_conflict', '同一任务的分析输入已冻结，不能替换。', 409)
        return old
    if parent_id: read(c, parent_id)
    snapshot = {'id': 'evidence-' + uuid.uuid4().hex, 'schema_version': 1,
                'purpose': kind, 'stage': stage, 'captured_at': now(), 'timezone': 'Asia/Shanghai',
                'model': model, 'prompt_version': prompt_version, 'messages': messages,
                'input_hash': digest(raw), 'sources': json.loads(encoded(list(sources))),
                'selection': json.loads(encoded(selection or {})), 'parent_id': parent_id}
    c.execute('INSERT INTO ai_evidence_snapshots VALUES (?,?)', (snapshot['id'], encoded(snapshot)))
    bind(c, kind, resource_id, snapshot['id'], stage)
    return snapshot


def read(c, snapshot_id):
    if not exists(c, 'ai_evidence_snapshots'): fail('not_found', '分析依据不存在。', 404)
    row = c.execute('SELECT data FROM ai_evidence_snapshots WHERE id=?', (snapshot_id,)).fetchone()
    if not row: fail('not_found', '分析依据不存在。', 404)
    value = json.loads(row[0])
    if digest(encoded(value['messages'])) != value['input_hash']:
        fail('evidence_hash', '分析依据校验失败，已停止调用。', 409)
    return value


def bind(c, kind, resource_id, snapshot_id, stage='input'):
    if kind not in KINDS: raise ValueError('Unknown evidence resource')
    read(c, snapshot_id)
    row = c.execute('SELECT snapshot_id FROM ai_evidence_links WHERE kind=? AND resource_id=? AND stage=?',
                    (kind, str(resource_id), stage)).fetchone()
    if row and row[0] != snapshot_id: fail('evidence_conflict', '结果已有其他分析依据，未覆盖。', 409)
    if not row:
        c.execute('INSERT INTO ai_evidence_links VALUES (?,?,?,?)', (kind, str(resource_id), stage, snapshot_id))


def link_statement(kind, resource_id, snapshot_id, stage='input'):
    """随原发布日志在同一数据库事务内保存结果引用，不把快照写入正式教材。"""
    if kind not in KINDS: raise ValueError('Unknown evidence resource')
    # 重放允许同一引用；不同输入触发 NOT NULL 约束，使原发布事务整体回滚。
    return ('INSERT INTO ai_evidence_links VALUES (?,?,?,?) ON CONFLICT(kind,resource_id,stage) DO UPDATE SET '
            'snapshot_id=CASE WHEN ai_evidence_links.snapshot_id=excluded.snapshot_id THEN excluded.snapshot_id ELSE NULL END',
            [kind, str(resource_id), stage, snapshot_id])


def linked(c, kind, resource_id):
    if kind not in KINDS: fail('invalid', '分析来源类型无效。', 422)
    if not exists(c, 'ai_evidence_links'): return []
    ids = [r[0] for r in c.execute(
        'SELECT snapshot_id FROM ai_evidence_links WHERE kind=? AND resource_id=? ORDER BY stage',
        (kind, str(resource_id)))]
    return sorted([read(c, sid) for sid in dict.fromkeys(ids)],key=lambda s:s['captured_at'])


def metadata(c, kind, resource_id):
    ids=[]
    if exists(c,'ai_evidence_links'):
        ids=list(dict.fromkeys(r[0] for r in c.execute('SELECT snapshot_id FROM ai_evidence_links WHERE kind=? AND resource_id=? ORDER BY stage',(kind,str(resource_id)))))
    return {'evidence_snapshot_ids':ids,'evidence_status':'available' if ids else 'legacy'}


def release(c, kind, resource_id):
    if not exists(c, 'ai_evidence_links'): return
    ids = [r[0] for r in c.execute('SELECT snapshot_id FROM ai_evidence_links WHERE kind=? AND resource_id=?', (kind, str(resource_id)))]
    c.execute('DELETE FROM ai_evidence_links WHERE kind=? AND resource_id=?', (kind, str(resource_id)))
    for sid in ids:
        if not c.execute('SELECT 1 FROM ai_evidence_links WHERE snapshot_id=?', (sid,)).fetchone():
            c.execute('DELETE FROM ai_evidence_snapshots WHERE id=?', (sid,))


def capture(connect, kind, resource_id, messages, cfg, **options):
    with connect() as c: return freeze(c, kind, resource_id, messages, cfg['model'], **options)


def messages(connect, snapshot_id):
    with connect() as c: return read(c, snapshot_id)['messages']


def register(app):
    from fastapi import APIRouter, Query, Depends, Response
    def private(response: Response):response.headers['Cache-Control']='no-store'
    router = APIRouter(prefix='/api/ai/evidence', dependencies=[Depends(private)])

    def display(c, value):
        from history_sources import availability
        cache={}
        return {**value, 'sources': [dict(s, availability=availability(c, s, cache, getattr(app.state,'ai_evidence_resolvers',{}))) for s in value['sources']]}

    @router.get('')
    def by_resource(kind: str = Query(max_length=40), resource_id: str = Query(max_length=600)):
        with connection() as c:
            values = linked(c, kind, resource_id)
            removed = False
            if not values and kind == 'behavior-report' and exists(c, 'behavior_report_jobs'):
                row = c.execute('SELECT data FROM behavior_report_jobs WHERE id=?', (resource_id,)).fetchone()
                removed = bool(row and json.loads(row[0]).get('result_deleted'))
            return {'items': [display(c, value) for value in values], 'legacy': not bool(values) and not removed,
                    'message': '报告已删除，对应分析依据已解除引用。' if removed else LEGACY if not values else ''}

    @router.get('/{snapshot_id}')
    def detail(snapshot_id: str):
        with connection() as c: return display(c, read(c, snapshot_id))

    app.include_router(router)
