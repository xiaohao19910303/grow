"""Private source-confirmation receipts travel in the source publication journal."""
from contextvars import ContextVar
import hashlib
import json
import uuid

pending_event = ContextVar('action_source_event', default=None)


def event_sql(event):
    if not event:
        return []
    from action_plans import encoded
    return [('INSERT INTO action_content_events VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
             [event['event_id'], event['request_key'], encoded(event)])]


def confirm_source(store, target, data, save):
    """The source save and receipt commit together; action sync may be retried."""
    from action_plans import connection, encoded, clock, get, same_target, fail, with_content_completion
    if not getattr(store, 'remote', False):
        return save()
    key=data.get('key') or str(uuid.uuid4())
    if not isinstance(key,str) or not 1<=len(key)<=160:fail(422,'确认请求编号无效。')
    signature=hashlib.sha256(encoded({'target':target,'data':data}).encode()).hexdigest()
    with store.lock():
        with connection() as c:
            row=c.execute('SELECT data FROM action_content_events WHERE request_key=?',(key,)).fetchone()
            event=json.loads(row[0]) if row else None
            if event:
                if event['request_hash']!=signature:fail(409,'确认请求编号已用于其他内容。')
            else:
                owner=c.execute('SELECT current_schema()').fetchone()[0]
                event=dict(event_id='source-'+uuid.uuid4().hex,request_key=key,request_hash=signature,owner=owner,
                           normalized_target=target,confirmed_at=clock().isoformat(),origin_action_id=data.get('origin_action_id'))
                if event['origin_action_id']:
                    plan=get(c,event['origin_action_id'])
                    if plan['completion_mode']!='content' or not same_target(plan['target'],target):fail(422,'来源与行动不匹配。')
                    event.update(planned_date_at_confirmation=plan['start_date'],timezone_at_confirmation=plan['timezone'])
        if row:
            return with_content_completion({**event.get('source_result',{}),'source_event_id':event['event_id'],'replayed':True},target,event['event_id'])
        token=pending_event.set(event)
        try:
            saved=save()
        finally:
            pending_event.reset(token)
        # This check does not manufacture a receipt after a source has saved.
        with connection() as c:
            stored=c.execute('SELECT 1 FROM action_content_events WHERE id=?',(event['event_id'],)).fetchone()
        if not stored:
            return {**saved,'arrangement_sync_error':'来源已保存，但该模块没有完成确认回执，请重新核对。'}
        return with_content_completion(saved,target,event['event_id'])
