"""Explicit, records-only source handoff. All identity comes from the login context."""
import hashlib
import hmac
import json
import math
from datetime import datetime
import os
import time
import uuid
from urllib.parse import urlsplit
import httpx
from copilot.core import fail
from tenancy import current_user

KINDS={'自由记录':'free','学习收获':'learning','遇到困难':'difficulty','决策回顾':'decision'}

def canonical(value):
    if isinstance(value,dict):
        return '{'+','.join(json.dumps(k,ensure_ascii=False)+':'+canonical(value[k]) for k in sorted(value,key=lambda x:x.encode('utf-16-be'))) +'}'
    if isinstance(value,list):return '['+','.join(canonical(v) for v in value)+']'
    if isinstance(value,float):
        if not math.isfinite(value):fail('invalid','历史中存在无效数字。',422)
        if value==0:return '0'
        if value.is_integer() and abs(value)<1e21:return str(int(value))
        text=repr(value).lower()
        if 'e' in text:
            base,exp=text.split('e');n=int(exp)
            if -6<=n<21:
                from decimal import Decimal
                return format(Decimal(text),'f').rstrip('0').rstrip('.') if n<0 else format(Decimal(text),'f')
            return base.rstrip('0').rstrip('.')+'e'+('+' if n>=0 else '')+str(n)
        return text
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def identity():
    user=current_user.get()
    if not user or not user.get('id'):fail('unauthorized','请先登录知行成长。',401)
    return user['id']

def configuration():
    url=os.getenv('LIGHTTICK_BRIDGE_URL','').rstrip('/');secret=os.getenv('GROW_RECORDS_BRIDGE_SECRET','');instance=os.getenv('GROW_RECORDS_SOURCE_ID','')
    try:
        parsed=urlsplit(url)
        valid=parsed.hostname and not(parsed.username or parsed.password or parsed.query or parsed.fragment) and parsed.path in ('','/') and (parsed.scheme=='https' or parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1'))
    except ValueError:valid=False
    return (url,secret,instance) if valid and len(secret)>=32 and instance else None

def call(body):
    from zook_web_auth import enabled
    if body.get('action') == 'claim' and enabled(): call({'action': 'preview', 'code': body.get('code')})
    config=configuration()
    if not config:fail('handoff_unavailable','记录联动尚未配置；已冻结内容保留，请稍后重试。',503)
    url,secret,instance=config;subject=identity();stamp=str(int(time.time()));nonce=uuid.uuid4().hex
    signature=hmac.new(secret.encode(),'\n'.join([instance,subject,stamp,nonce,canonical(body)]).encode(),hashlib.sha256).hexdigest()
    try:
        with httpx.Client(timeout=25,follow_redirects=False) as client:
            response=client.post(url+'/api/v1/lighttick/record-bridge',json=body,headers={'X-Grow-Instance':instance,'X-Grow-Account-Id':subject,'X-Grow-Timestamp':stamp,'X-Grow-Nonce':nonce,'X-Grow-Signature':signature})
        payload=response.json()
    except (httpx.HTTPError,ValueError):fail('handoff_unknown','连接结果尚未确认。内容已保留，请重试恢复。',503)
    if not isinstance(payload,dict):fail('handoff_unknown','联动响应无效，请重试恢复。',503)
    if response.status_code>=400:fail(str(payload.get('code','handoff_rejected')),str(payload.get('message','记录联动暂未完成。'))[:200],response.status_code)
    result = payload.get('data')
    if body.get('action') == 'preview':
        from zook_web_auth import assert_target
        assert_target(result.get('target_user_id'))
    return result

def state(store):
    with store.conn() as c:row=c.execute('SELECT data FROM reflection_link_state WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'phase':'local'}

def put(store,value):
    with store.conn() as c:c.execute('INSERT INTO reflection_link_state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data',(canonical(value),))

def assert_writable(store):
    if state(store).get('phase') not in ('local','preview'):fail('records_frozen','记录已交接或正在恢复，请刷新连接状态；输入保留。',423)

def normalized(entry,current=None):
    base=current or entry;summary=entry.get('adopted_summary');basis=entry.get('summary_basis_version')
    value={k:entry.get(k,base.get(k)) for k in ('record_date','raw_text','guided_answers','tags')}
    value.update(id=entry.get('entry_id',entry.get('id')),version=entry['version'],prompt_kind=KINDS.get(entry.get('prompt_kind'),entry.get('prompt_kind')),created_at=base['created_at'],updated_at=entry.get('updated_at',entry['created_at']))
    if base is entry and entry.get('archived_at'):value['archived_at']=entry['archived_at']
    if summary:
        value['adopted_summary']='\n\n'.join(s.get('text','') for s in summary.get('sections',[])) if isinstance(summary,dict) else summary
        if basis is None:
            value.pop('adopted_summary',None)
        else:value['summary_basis_version']=basis
    return value

def package(store,operation):
    config=configuration()
    if not config:fail('handoff_unavailable','请先配置记录联动。',503)
    entries=sorted(store.rows('reflection_entries'),key=lambda e:e['id']);attempts=store.rows('reflection_ai_attempts');operations=store.rows('reflection_operations')
    if any(a.get('status') in ('queued','generating') for a in attempts) or any(o.get('state')!='done' for o in operations):fail('handoff_busy','请等待 AI 和未完成写入结束后再连接。')
    result={'format_version':1,'source_instance':config[2],'source_subject':identity(),'operation_id':operation,'entries':[]}
    for entry in entries:
        versions=sorted(store.versions(entry['id']),key=lambda v:v['version']);current=normalized(entry);observed=[]
        for version in versions:
            v=normalized(version,entry)
            if version['version']==entry['version']:
                if any(version.get(k)!=entry.get(k) for k in ('raw_text','record_date','prompt_kind','guided_answers','tags','adopted_summary')):fail('history_conflict','当前记录与已存版本不一致，请先核对原始历史。')
                # Current observed state supplies lifecycle metadata; original version data remains exact in private_history.
                v=current.copy()
            observed.append(v)
        seen={v['version'] for v in observed}|{entry['version']}
        private={'normalization':{'summary_basis_missing_versions':sorted({v['version'] for v in versions if v['version']!=entry['version'] and v.get('adopted_summary') and v.get('summary_basis_version') is None})},'entry':entry,'versions':versions,'attempts':[a for a in attempts if a.get('entry_id')==entry['id']],
                 'operations':[{k:o[k] for k in ('id','state','request_hash','result','created_at') if k in o} for o in operations if entry['id'] in canonical(o.get('result',{}))]}
        result['entries'].append({'source_id':entry['id'],'record':current,'versions':observed,'missing_versions':[n for n in range(1,entry['version']) if n not in seen],'private_history':private})
    if len(canonical(result).encode())>4*1024*1024:fail('handoff_capacity','记录历史超过本次接管容量，原数据保留。',422)
    return result

def public(value):
    return {k:value[k] for k in ('phase','preview_id','target_user_id','binding_id','snapshot_hash','counts','receipt') if k in value}

def preview(store,code):
    target=call({'action':'preview','code':code});operation='records-'+uuid.uuid4().hex
    with store.lock(handoff=True):
        old=state(store)
        if old['phase'] not in ('local','preview'):fail('handoff_pending','已有记录交接，请重试恢复。')
        snapshot=package(store,operation)
        value={'phase':'preview','preview_id':uuid.uuid4().hex,'operation_id':operation,'code_hash':digest(code),'expires_at':min(time.time()+300,datetime.fromisoformat(target['expires_at'].replace('Z','+00:00')).timestamp()),'target_user_id':target['target_user_id'],'snapshot_hash':digest(snapshot),'counts':{'records':len(snapshot['entries']),'versions':sum(len(e['versions']) for e in snapshot['entries']),'history_gaps':sum(len(e['missing_versions']) for e in snapshot['entries'])}}
        put(store,value);return public(value)

def confirm(store,code,preview_id,consent):
    if consent is not True:fail('consent_required','请先核对目标账户并确认转入。',422)
    with store.lock(handoff=True):
        old=state(store)
        if old['phase']!='preview' or old.get('preview_id')!=preview_id or old.get('code_hash')!=digest(code) or old['expires_at']<time.time():fail('preview_expired','预览已过期，请重新核对。')
        target=call({'action':'preview','code':code})
        if target.get('target_user_id')!=old['target_user_id']:fail('target_changed','目标账户已变化，请重新核对。')
        snapshot=package(store,old['operation_id'])
        if digest(snapshot)!=old['snapshot_hash']:fail('source_changed','预览后记录已变化，请重新核对。')
        # Persist the write barrier and exact package before any remote stage request.
        put(store,{**old,'phase':'preparing','snapshot':snapshot,'code':code})
    return finish(store)

def finish(store,code=None):
    with store.lock(handoff=True):
        value=state(store)
        if value['phase']=='active':return public(value)
        if value['phase'] not in ('preparing','frozen'):fail('handoff_missing','没有待恢复的记录交接。')
        if code:
            target=call({'action':'preview','code':code})
            if target['target_user_id']!=value['target_user_id']:fail('target_changed','恢复码必须来自原目标账户。')
            value['code']=code;put(store,value)
        if not value.get('binding_id'):
            from copilot.core import Problem
            try:binding=call({'action':'status'})
            except Problem as error:
                if error.status!=404:raise
                binding=call({'action':'claim','code':value['code'],'operation_id':value['operation_id']})
            if binding.get('phase')=='cancelled':binding=call({'action':'claim','code':value['code'],'operation_id':value['operation_id']})
            if binding.get('operation_id')!=value['operation_id'] or binding.get('target_user_id')!=value['target_user_id']:fail('binding_changed','目标绑定与本次交接不一致。')
            value['binding_id']=binding['binding_id'];put(store,value)
        base={k:value[k] for k in ('binding_id','operation_id','snapshot_hash')}
        if value['phase']=='preparing':
            call({'action':'stage',**base,'snapshot':value['snapshot']})
            receipt={'scope':'records','phase':'frozen',**base,'source_instance':value['snapshot']['source_instance'],'source_subject':value['snapshot']['source_subject']}
            receipt['signature']=hmac.new(configuration()[1].encode(),canonical(receipt).encode(),hashlib.sha256).hexdigest()
            value.update(phase='frozen',freeze_receipt=receipt);put(store,value)
        receipt=call({'action':'activate',**base,'freeze_receipt':value['freeze_receipt']})
        if any(receipt.get(k)!=v for k,v in base.items()) or receipt.get('target_user_id')!=value['target_user_id'] or receipt.get('phase')!='active' or receipt.get('source_counts',{}).get('records')!=value['counts']['records'] or receipt.get('source_counts',{}).get('versions')!=value['counts']['versions']:fail('receipt_mismatch','激活回执尚未核验，来源继续冻结，请重试。',503)
        value.update(phase='active',receipt=receipt);value.pop('code',None);put(store,value);return public(value)


def cancel(store):
    with store.lock(handoff=True):
        value=state(store)
        if value['phase']=='preview':put(store,{'phase':'local'});return {'phase':'local'}
        if value['phase'] not in ('preparing','frozen'):fail('handoff_active','已激活记录须先在目标端进入只读恢复并导出最新数据。')
        from copilot.core import Problem
        try:binding=call({'action':'status'})
        except Problem as error:
            if error.status!=404:raise
            binding=None
        if binding and binding.get('phase')!='cancelled':
            if binding.get('operation_id')!=value['operation_id'] or binding.get('target_user_id')!=value['target_user_id']:fail('binding_changed','绑定发生变化，来源保持冻结。')
            result=call({'action':'cancel','binding_id':binding['binding_id'],'operation_id':value['operation_id']})
            if result.get('phase')!='cancelled':fail('handoff_unknown','取消尚未确认，来源保持冻结。',503)
        put(store,{'phase':'local','cancelled_handoff':{k:v for k,v in value.items() if k!='code'}})
        return {'phase':'local'}
