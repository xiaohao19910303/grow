"""Internal C3 export only. Public pairing/import gates remain closed.

Call under the actions write lock. The table lock gives one consistent cut across
source publication and action facts; this function never freezes a writer.
"""
import json
from action_plans import connection, encoded, fail, same_target

COLLECTIONS=('plans','records','reviews','reports','operations','claims','content_sources','content_events')
EVENT_FIELDS=('event_id','normalized_target','confirmed_at','origin_action_id',
              'planned_date_at_confirmation','timezone_at_confirmation','consumed_by','request_key','request_hash')


def snapshot_v2(source):
    from action_link import identity
    if identity()!=source:fail(403,'来源账号与当前登录身份不匹配。')
    if not isinstance(source,str) or not 1<=len(source)<=160:
        fail(422,'来源账号无效。')
    with connection(True,allow_link=True) as c:
        return export_locked(c,source)


def export_locked(c,source):
    from action_link import snapshot, state
    if state(c)[0].get('phase')!='local':
        fail(409,'只允许导出尚未接管的本地账号。')
    require_settled_publications(c)
    # Source publication inserts its receipt in the same PostgreSQL commit.
    c.execute('LOCK TABLE action_content_events IN SHARE MODE')
    if c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0] or c.execute('SELECT count(*) FROM action_source_contexts').fetchone()[0]:
        fail(409,'账号已有连接端投递状态，禁止混入新接管。')
    data=snapshot(c)
    if any(r.get('state')=='generating' for r in data['reports']):
        fail(409,'请先等待正在生成的总结结束。')
    owner=c.execute('SELECT current_schema()').fetchone()[0]
    events=[]
    for row in c.execute('SELECT data FROM action_content_events ORDER BY id'):
        event=json.loads(row[0])
        if event.get('owner')!=owner or event.get('delivery'):
            fail(409,'来源回执归属不匹配，禁止导出。')
        events.append({**{k:event[k] for k in EVENT_FIELDS if k in event},'owner':source})
    for event in events:
        value=event['normalized_target']
        keys=('kind','course') if value['kind']=='article' else ('kind','plan_id','lesson_no')
        event['normalized_target']={k:value[k] for k in keys}
    sources=[]
    for value in [p.get('target') for p in data['plans']]+[e['normalized_target'] for e in events]:
        if value and value.get('kind') in ('article','plan'):
            # Reuse the private source normalization; discard irrelevant kind fields.
            keys=('kind','course') if value['kind']=='article' else ('kind','plan_id','lesson_no')
            value={k:value[k] for k in keys}
            if not any(same_target(value,t) for t in sources):sources.append(value)
    result={**data,'snapshot_version':2,'source_account_id':source,
            'content_sources':sorted(sources,key=encoded),'content_events':events}
    if len(encoded(result).encode())>4*1024*1024:fail(422,'历史数据超过接管容量，原数据保留。')
    return result


def require_settled_publications(c):
    # A crashed publisher has released its advisory lock but may still have a
    # durable journal whose source-event SQL has not committed. Never freeze past
    # that journal. Recovery stays with the owning source store and original key.
    for table in ('learning_publications','cloud_publications','reading_records'):
        if c.execute('SELECT to_regclass(?)',(table,)).fetchone()[0] is None:continue
        value="replace(data,?,?)::jsonb"
        prefix=(value+"->>'type'='export' AND ") if table=='reading_records' else ''
        params=[r'\u0000',r'\ufffd']*(2 if prefix else 1)
        if c.execute(f"SELECT 1 FROM {table} WHERE {prefix}{value}->>'state' IS DISTINCT FROM 'done' LIMIT 1",params).fetchone():
            fail(409,'仍有来源发布日志待恢复，请先用原来源请求完成恢复，再重新预检；当前写入方未冻结。','STATE_CONFLICT',reason='SOURCE_PUBLICATION_PENDING')
