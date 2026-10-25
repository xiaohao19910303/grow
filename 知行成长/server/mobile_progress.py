"""Bound-source, restart-safe publication of formal plan progress, without notes."""
import hashlib
import json
import os
from urllib.parse import urlsplit

import action_plans as actions
from action_link import call, identity, state

FIELDS=('total_lessons','published_lessons','completed_lessons','percent')


def source_url():
    value=os.getenv('GROW_PUBLIC_URL','').strip().rstrip('/')+'/'
    parsed=urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.netloc or
            parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1'))):
        return None
    return value


def snapshot(store):
    from learning_actions import projection
    result=[]
    # Formal edits use the same store lock. Progress never publishes course body,
    # GitHub credentials, private notes, feedback or model-generated suggestions.
    with store.lock():
        plans=store.rows('learning_plans')
        if len(plans)>100:raise ValueError('Mobile plan progress exceeds its current capacity')
        for item in sorted(plans,key=lambda p:p['id']):
            p=projection(store,item['id'])
            result.append({**{k:p[k] for k in ('id','name','version','status',*FIELDS)},
                           'stages':[{k:s[k] for k in ('number','title',*FIELDS)} for s in p['stages']]})
    return result


def sync(store):
    origin=source_url()
    if not origin:return
    with actions.connection() as c:link,_=state(c)
    # v2 consent includes read-only formal-plan progress; older bindings do not.
    if link.get('phase')!='active' or link.get('snapshot_version')!=2:return
    plans=snapshot(store)
    data={'web_url':origin,'plans':plans}
    signature=hashlib.sha256(actions.encoded(data).encode()).hexdigest()
    with actions.connection(True,allow_link=True) as c:
        current,_=state(c)
        if current.get('phase')!='active' or current.get('binding_id')!=link['binding_id']:return
        c.execute('CREATE TABLE IF NOT EXISTS action_mobile_progress (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
        row=c.execute('SELECT data FROM action_mobile_progress WHERE id=1').fetchone()
        old=json.loads(row[0]) if row else {}
        if old.get('signature')==signature and old.get('binding_id')==link['binding_id']:
            if old.get('delivered'):return
            pending=old
        else:
            revision=old.get('revision',0)+1
            payload=dict(action='learning-progress',action_schema_version=2,binding_id=link['binding_id'],source_revision=revision,
                         observed_at=actions.clock().isoformat(),**data)
            pending=dict(signature=signature,binding_id=link['binding_id'],revision=revision,payload=payload,delivered=False)
            c.execute('INSERT INTO action_mobile_progress VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(actions.encoded(pending),))
    receipt=call(identity(),pending['payload'])
    expected_hash=hashlib.sha256(actions.encoded({k:v for k,v in pending['payload'].items() if k not in ('action','action_schema_version','binding_id')}).encode()).hexdigest()
    if (not isinstance(receipt,dict) or receipt.get('accepted') is not True or receipt.get('binding_id')!=link['binding_id'] or
            receipt.get('target_user_id')!=link['target_user_id'] or receipt.get('source_revision')!=pending['revision'] or receipt.get('payload_hash')!=expected_hash):
        raise ValueError('Mobile progress receipt does not match its bound source snapshot')
    with actions.connection(True,allow_link=True) as c:
        row=c.execute('SELECT data FROM action_mobile_progress WHERE id=1').fetchone()
        if row:
            latest=json.loads(row[0])
            if latest.get('binding_id')==pending['binding_id'] and latest.get('revision')==pending['revision']:
                latest['delivered']=True
                c.execute('UPDATE action_mobile_progress SET data=? WHERE id=1',(actions.encoded(latest),))
