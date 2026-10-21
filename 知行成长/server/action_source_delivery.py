"""Private, tenant-scoped Grow -> Zook source outbox. Never a local action writer."""
from datetime import datetime, timedelta
import json
import re

from action_plans import connection, encoded, fail

def clock():
    import action_plans
    return action_plans.clock()


def prepare(target, origin):
    from action_link import state, identity, call
    with connection() as c:link,_=state(c)
    if link.get('phase')!='active':return None
    delivery=dict(binding_id=link['binding_id'],target_user_id=link['target_user_id'],source_account_id=identity())
    if origin:
        try:
            context=call(identity(),dict(action='source-context',action_schema_version=2,binding_id=link['binding_id'],
                origin_action_id=origin,normalized_target=target))
            cache_context(context,target,origin,link)
        except Exception:
            with connection() as c:
                row=c.execute('SELECT data FROM action_source_contexts WHERE id=?',(origin,)).fetchone()
                context=json.loads(row[0]) if row else None
        if context and context.get('binding_id')==link['binding_id'] and context.get('source_account_id')==identity() and context.get('normalized_target')==target and context.get('origin_action_id')==origin and datetime.fromisoformat(context.get('expires_at','1970-01-01T00:00:00+00:00'))>=clock():
            delivery['origin_context']=context['origin_context']
        else:delivery['blocked_reason']='ORIGIN_CONTEXT_REQUIRED'
    return delivery


def cache_context(context,target,origin,link):
    from action_link import identity
    if not isinstance(context,dict) or not all(isinstance(context.get(k),str) for k in ('issued_at','expires_at','origin_context')) or context.get('binding_id')!=link['binding_id'] or context.get('source_account_id')!=identity() or context.get('origin_action_id')!=origin or context.get('normalized_target')!=target or not isinstance(context.get('origin_context'),str):
        fail(503,'来源行动上下文尚未通过核对。')
    try:
        start=datetime.fromisoformat(context['issued_at']);end=datetime.fromisoformat(context['expires_at'])
        if start.tzinfo is None or end.tzinfo is None or end<=start:raise ValueError('unscoped timestamp')
    except (ValueError,TypeError):fail(503,'来源行动上下文时间无效。')
    with connection(True,allow_link=True) as c:
        c.execute('INSERT INTO action_source_contexts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data',(origin,encoded(context)))


def outbox_sql(event):
    delivery=event.get('delivery')
    if not delivery:return []
    e={k:event[k] for k in ('event_id','normalized_target','confirmed_at','origin_action_id')}
    e['source_proof']={'version':1,'confirmation':'article_read' if e['normalized_target']['kind']=='article' else 'lesson_completed'}
    if delivery.get('origin_context'):e['origin_context']=delivery['origin_context']
    payload=dict(action='source-confirmation',action_schema_version=2,binding_id=delivery['binding_id'],event=e)
    state='blocked' if delivery.get('blocked_reason') else 'pending'
    data={k:delivery[k] for k in ('source_account_id','target_user_id')}
    if delivery.get('blocked_reason'):data['reason']=delivery['blocked_reason']
    return [('INSERT INTO action_source_outbox VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING',
             [event['event_id'],encoded(payload),state,0,event['confirmed_at'],None,encoded(data)])]


def valid_receipt(receipt,payload,data):
    from action_link import fingerprint
    if not isinstance(receipt,dict) or set(receipt)!=set(('accepted','binding_id','target_user_id','event_id','payload_hash','status','completed_arrangements','record_id','reason')):return False
    completed=receipt.get('completed_arrangements')
    return (receipt.get('accepted') is True and receipt.get('binding_id')==payload['binding_id'] and
        receipt.get('target_user_id')==data['target_user_id'] and receipt.get('event_id')==payload['event']['event_id'] and
        receipt.get('payload_hash')==fingerprint(payload['event']) and receipt.get('status') in ('pending','completed') and
        isinstance(completed,list) and len(completed)<=1 and all(isinstance(x,str) and x.startswith('action-') for x in completed) and
        ((receipt['status']=='completed' and len(completed)==1 and isinstance(receipt.get('record_id'),str) and re.fullmatch(r'execution-[a-zA-Z0-9-]+',receipt['record_id']) and (not payload['event'].get('origin_action_id') or completed==[payload['event']['origin_action_id']])) or
         (receipt['status']=='pending' and not completed and receipt.get('record_id') is None)))


def retry_due(force=False,event_id=None,limit=10,retry_blocked=False):
    from action_link import state,identity,call
    now=clock()
    with connection() as c:
        link,_=state(c)
        if link.get('phase')!='active':return []
        states="('pending','delivered','blocked')" if retry_blocked else "('pending','delivered')"
        rows=c.execute('SELECT * FROM action_source_outbox WHERE state IN '+states+' ORDER BY next_attempt,event_id').fetchall()
    results=[]
    for old in rows:
        if len(results)>=limit:break
        if event_id and old['event_id']!=event_id:continue
        if not force and old['next_attempt']>now.isoformat():continue
        # A short persistent lease prevents hot loops; a crashed sender is retried.
        with connection(True,allow_link=True) as c:
            row=c.execute('SELECT * FROM action_source_outbox WHERE event_id=? FOR UPDATE',(old['event_id'],)).fetchone()
            if row['state'] not in (('pending','delivered','blocked') if retry_blocked else ('pending','delivered')) or (not force and row['next_attempt']>now.isoformat()):continue
            payload=json.loads(row['payload']);data=json.loads(row['data'])
            if row['state']=='blocked' and data.get('reason') in ('ORIGIN_CONTEXT_REQUIRED','SOURCE_BINDING_CHANGED','SOURCE_EVENT_CONFLICT','SOURCE_PROOF_INVALID'):continue
            if payload['binding_id']!=link.get('binding_id') or data['source_account_id']!=identity() or data['target_user_id']!=link.get('target_user_id'):
                c.execute("UPDATE action_source_outbox SET state='blocked',data=? WHERE event_id=?",(encoded({**data,'reason':'SOURCE_BINDING_CHANGED'}),row['event_id']));continue
            attempts=row['attempts']+1
            c.execute('UPDATE action_source_outbox SET attempts=?,next_attempt=? WHERE event_id=?',
                (attempts,(now+timedelta(seconds=min(3600,15*2**min(attempts,8)))).isoformat(),row['event_id']))
        receipt=None;status='pending';error=None
        try:
            if row['receipt']:
                body=dict(action='source-reconcile',action_schema_version=2,binding_id=payload['binding_id'],event_id=row['event_id'])
            else:body=payload
            receipt=call(identity(),body)
            if not valid_receipt(receipt,payload,data):fail(503,'确认回执校验未通过。')
            status='completed' if receipt['status']=='completed' else 'delivered'
        except Exception as exc:
            receipt=None;error=getattr(exc,'code','SOURCE_DELIVERY_UNCONFIRMED')
            # A previously accepted inbox remains accepted even if reconciliation is offline.
            status=row['state']
            if getattr(exc,'status_code',None) in (401,403,404,409,422):status='blocked'
        with connection(True,allow_link=True) as c:
            latest=c.execute('SELECT state FROM action_source_outbox WHERE event_id=?',(row['event_id'],)).fetchone()
            if latest[0]!='completed':
                c.execute('UPDATE action_source_outbox SET state=?,receipt=COALESCE(?,receipt),data=? WHERE event_id=?',
                    (status,encoded(receipt) if receipt else None,encoded({**data,'reason':error or (receipt or {}).get('reason')}),row['event_id']))
        results.append(row['event_id'])
    return results


def completion(event_id):
    retry_due(force=True,event_id=event_id,limit=1)
    with connection() as c:row=c.execute('SELECT state,receipt,data FROM action_source_outbox WHERE event_id=?',(event_id,)).fetchone()
    if not row:return None
    receipt=json.loads(row['receipt']) if row['receipt'] else {}
    reason=json.loads(row['data']).get('reason')
    message=('来源已保存；缺少行动上下文证明，请恢复连接后重新打开内容并再次明确确认。' if reason=='ORIGIN_CONTEXT_REQUIRED' else '来源已保存，连接完成待核对；请保留本次确认，稍后重试。')
    return {'source_event_id':event_id,'completed_arrangements':receipt.get('completed_arrangements',[]),
        'source_delivery_state':row['state'],**({} if row['state']=='completed' else {'arrangement_sync_error':message})}


def list_deliveries():
    with connection() as c:
        return [{'event_id':r['event_id'],'state':r['state'],'attempts':r['attempts'],'next_attempt':r['next_attempt'],
                 'reason':json.loads(r['data']).get('reason'),'receipt':json.loads(r['receipt']) if r['receipt'] else None}
                for r in c.execute('SELECT * FROM action_source_outbox ORDER BY next_attempt,event_id LIMIT 100')]
