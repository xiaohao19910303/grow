"""Dormant C3 coordinator. No public route invokes preflight/stage_v2.

The production bridge still rejects handoff. Tests inject a localhost-only,
transport-authenticated driver; this module adds no rollout switch.
"""
from contextlib import contextmanager
import uuid
import db
from action_plans import connection,fail,encoded
from action_link import identity,state,put,fingerprint,public,call
from action_handoff import snapshot_v2,export_locked,COLLECTIONS


@contextmanager
def source_fence(shared=True):
    # Finish first-use DDL before source publication opens independent connections.
    with connection():pass
    with db.connect() as c:
        lock='pg_advisory_xact_lock_shared' if shared else 'pg_advisory_xact_lock'
        c.execute(f"SELECT {lock}(hashtextextended(current_schema() || ':action-source-cutover',0))")
        if shared and state(c)[0].get('phase')=='pending':
            fail(503,'行动正在接管，本次来源确认尚未提交；请保留原请求，接管恢复后重试。','SOURCE_DELIVERY_UNAVAILABLE',retryable=True,submitted=False)
        yield


def scoped(source):
    if identity()!=source:fail(403,'来源账号与当前登录身份不匹配。')


def counts(data):return {key:len(data[key]) for key in COLLECTIONS}


def checked(receipt,expected,imported=False):
    if imported:
        from datetime import datetime
        try:
            stamp=datetime.fromisoformat(receipt.get('imported_at','')) if isinstance(receipt,dict) else None
            if not stamp or stamp.tzinfo is None:raise ValueError()
        except (ValueError,TypeError):fail(503,'接管完成时间无效，请保留只读状态并重试核对。')
    fields=('binding_id','target_user_id','snapshot_hash','source_counts','target_version')
    phase_field='imported_at' if imported else 'validated'
    if not isinstance(receipt,dict) or set(receipt)!=set(fields)|{phase_field}:
        fail(503,'接管回执阶段或字段不符合合同，请保留当前状态并重新核对。')
    if isinstance(receipt,dict):
        source_counts=receipt.get('source_counts')
        if not isinstance(source_counts,dict) or set(source_counts)!=set(COLLECTIONS) or any(type(v) is not int or v<0 for v in source_counts.values()):
            fail(503,'接管数量回执无效，请保留当前写入状态并重新核对。')
    if (not isinstance(receipt,dict) or any(receipt.get(k)!=expected.get(k) for k in fields) or
        type(receipt.get('target_version')) is not int or not 0<=receipt['target_version']<=2147483647 or
        not isinstance(receipt.get('binding_id'),str) or not 1<=len(receipt['binding_id'])<=160 or
        not isinstance(receipt.get('target_user_id'),str) or not 1<=len(receipt['target_user_id'])<=160 or
        (not imported and receipt.get('validated') is not True) or (imported and not receipt.get('imported_at'))):
        fail(503,'接管回执尚未通过核对，原写入方和不可变备份保持原状态。')
    return receipt


def preflight_v2(source,binding_id,send=call):
    scoped(source)
    data=snapshot_v2(source)
    expected=dict(binding_id=binding_id,snapshot_hash=fingerprint(data),source_counts=counts(data))
    receipt=send(source,dict(action='import-preflight',snapshot=data,snapshot_hash=expected['snapshot_hash'],binding_id=binding_id))
    if isinstance(receipt,dict):expected.update(target_user_id=receipt.get('target_user_id'),target_version=receipt.get('target_version'))
    checked(receipt,expected)
    proposal={**expected,'preview_id':str(uuid.uuid4())}
    with connection(True,allow_link=True) as c:
        current,_=state(c)
        if current.get('phase')!='local':fail(409,'接管状态已变化，请刷新。')
        # Snapshot can change while the network is in flight; stage checks again.
        put(c,{**current,'preview_v2':proposal})
    return proposal


def stage_v2(source,preview_id):
    scoped(source)
    # This ordering matters: a source publication may take the actions-write lock
    # when it records local completion. Wait for it BEFORE acquiring that lock.
    with source_fence(shared=False):
        with connection(True,allow_link=True) as c:
            current,backup=state(c)
            if current.get('phase') in ('pending','active'):
                if current.get('preview_id')!=preview_id:fail(409,'接管预览已变化。')
                return public(current)
            proposal=current.get('preview_v2',{})
            if proposal.get('preview_id')!=preview_id:fail(409,'请先重新预检接管范围。')
            data=export_locked(c,source)
            if fingerprint(data)!=proposal.get('snapshot_hash') or counts(data)!=proposal.get('source_counts'):
                fail(409,'来源确认或行动已变化，请重新预检；当前写入方未冻结。')
            # Immutable package and writer fence commit together, before any import.
            put(c,{**proposal,'phase':'pending','snapshot_version':2,'source_account_id':source,'counts':counts(data)},data)
    return public({**proposal,'phase':'pending','counts':proposal['source_counts']})


def finish_v2(source,send=call):
    scoped(source)
    with connection() as c:link,backup=state(c)
    if link.get('phase')=='active':return public(link)
    if link.get('phase')!='pending' or link.get('snapshot_version')!=2 or not backup:fail(409,'没有待恢复的v2接管。')
    if link.get('source_account_id')!=source or fingerprint(backup)!=link.get('snapshot_hash') or counts(backup)!=link.get('source_counts'):
        fail(409,'接管备份校验失败，请保留当前只读状态并核对备份。')
    receipt=send(source,dict(action='import',snapshot=backup,snapshot_hash=link['snapshot_hash'],binding_id=link['binding_id'],target_version=link['target_version']))
    checked(receipt,link,imported=True)
    with connection(True,allow_link=True) as c:
        current,_=state(c)
        if current.get('snapshot_hash')!=link['snapshot_hash'] or current.get('binding_id')!=link['binding_id']:fail(409,'接管状态已变化。')
        if current.get('phase')=='active':return public(current)
        if current.get('phase')!='pending':fail(409,'接管状态已变化。')
        # Acknowledged imported events join the same durable C2 reconciliation
        # queue; their proof is the verified full-graph handoff, never a retrofitted
        # browser origin token. Start as delivered, so only reconciliation is sent.
        for event in backup['content_events']:
            wire={k:event.get(k) for k in ('event_id','normalized_target','confirmed_at','origin_action_id')}
            wire['source_proof']={'version':1,'confirmation':'article_read' if wire['normalized_target']['kind']=='article' else 'lesson_completed'}
            payload=dict(action='source-confirmation',action_schema_version=2,binding_id=link['binding_id'],event=wire)
            consumed=event.get('consumed_by');fact=next((r for r in backup['records'] if r.get('source_event_id')==event['event_id'] and r.get('record_kind')=='completion'),None)
            event_receipt=dict(accepted=True,binding_id=link['binding_id'],target_user_id=link['target_user_id'],event_id=event['event_id'],payload_hash=fingerprint(wire),status='completed' if consumed else 'pending',completed_arrangements=[consumed] if consumed else [],record_id=fact['id'] if fact else None,reason=None)
            data=dict(source_account_id=source,target_user_id=link['target_user_id'])
            from action_source_delivery import valid_receipt
            if not valid_receipt(event_receipt,payload,data):fail(409,'接管来源消费回执不一致，保持只读并保留备份。')
            c.execute('INSERT INTO action_source_outbox VALUES (?,?,?,?,?,?,?)',
                (event['event_id'],encoded(payload),'completed' if consumed else 'delivered',0,event['confirmed_at'],encoded(event_receipt),encoded(data)))
        put(c,{**current,'phase':'active','receipt':receipt})
    return public({**link,'phase':'active'})


def revalidate_v2(source,send=call):
    scoped(source)
    with connection() as c:link,backup=state(c)
    if link.get('phase')!='pending' or link.get('snapshot_version')!=2 or not backup:fail(409,'没有待重新预检的v2接管。')
    if fingerprint(backup)!=link.get('snapshot_hash') or counts(backup)!=link.get('source_counts'):fail(409,'接管备份校验失败。')
    receipt=send(source,dict(action='import-preflight',snapshot=backup,snapshot_hash=link['snapshot_hash'],binding_id=link['binding_id']))
    expected={**link,'target_version':receipt.get('target_version') if isinstance(receipt,dict) else None}
    checked(receipt,expected)
    with connection(True,allow_link=True) as c:
        current,frozen=state(c)
        if current.get('phase')!='pending' or current.get('snapshot_hash')!=link['snapshot_hash'] or current.get('binding_id')!=link['binding_id'] or current.get('target_version')!=link.get('target_version') or frozen!=backup:fail(409,'接管状态已变化，请重新核对。')
        put(c,{**current,'target_version':receipt['target_version']})
    return public(current)
