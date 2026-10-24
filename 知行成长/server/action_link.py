"""Verified Grow identity attestation and recoverable, single-writer Zook handoff."""
import hashlib
import hmac
import json
import os
import time
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from action_plans import Input, connection, encoded, fail
from tenancy import current_user


def identity():
    user=current_user.get()
    if not user or not user.get('id'):
        fail(401,'请先登录知行成长。')
    return user['id']


def configuration():
    url=os.getenv('LIGHTTICK_BRIDGE_URL','').rstrip('/')
    secret=os.getenv('GROW_ACTION_BRIDGE_SECRET','')
    try:
        parsed=urlsplit(url)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            return None
        if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
            return None
    except ValueError:
        return None
    return (url,secret) if len(secret)>=32 else None


def call(source,body):
    config=configuration()
    if not config:fail(503,'联动服务尚未配置，已接管的数据不会退回本地写入。')
    url,secret=config
    stamp=str(int(time.time()));nonce=str(uuid.uuid4())
    signature=hmac.new(secret.encode(),'\n'.join([source,stamp,nonce,encoded(body)]).encode(),hashlib.sha256).hexdigest()
    try:
        with httpx.Client(timeout=20,follow_redirects=False) as client:
            response=client.post(url+'/api/v1/lighttick/grow-bridge',json=body,headers={'X-Grow-Account-Id':source,'X-Grow-Timestamp':stamp,'X-Grow-Nonce':nonce,'X-Grow-Signature':signature})
        data=response.json()
    except (httpx.HTTPError,ValueError):
        fail(503,'联动请求尚未确认，请检查连接后重试。已保存的数据和接管备份均保留。')
    if not isinstance(data,dict):fail(503,'联动响应格式无效，已保存的数据保留。')
    if response.status_code>=400:
        fail(response.status_code,'LightTick：'+str(data.get('message','联动暂未完成，请稍后重试。'))[:200],str(data.get('code','REQUEST_REJECTED')))
    return data.get('data')


def state(c):
    row=c.execute('SELECT data,backup FROM action_link_state WHERE id=1').fetchone()
    return (json.loads(row[0]),json.loads(row[1]) if row[1] else None) if row else ({'phase':'local'},None)


def put(c,data,backup=None):
    c.execute('INSERT INTO action_link_state VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,backup=COALESCE(EXCLUDED.backup,action_link_state.backup)',(encoded(data),encoded(backup) if backup is not None else None))


def snapshot(c):
    from rhythm.store import has_data
    if has_data(c):
        fail(409,'当前接管合同不包含日常节奏数据，原数据保留；请等待连接端升级。','CONTRACT_UPGRADE_REQUIRED')
    # Source tables remain retained; this exact immutable package is the recovery backup.
    result={}
    for name,table in [('plans','action_plans'),('records','action_executions'),('reviews','action_reviews'),('reports','action_reports')]:
        result[name]=[json.loads(r[0]) for r in c.execute(f'SELECT data FROM {table} ORDER BY id')]
    if any(p.get('completion_mode','time')!='time' for p in result['plans']):
        fail(422,'当前客户端联动首版支持计时计划；你的数据包含按内容或勾选完成的日程，暂不接管，原计划和记录均保留。')
    result['operations']=[dict(key=r['key'],hash=r['hash'],result=json.loads(r['result'])) for r in c.execute('SELECT * FROM action_operations ORDER BY key')]
    result['claims']=[dict(key=r['key'],claimed_at=r['claimed_at']) for r in c.execute('SELECT * FROM action_reminder_claims ORDER BY key')]
    if len(encoded(result).encode())>4*1024*1024:
        fail(422,'历史数据超过首版接管容量，原数据保留，请先联系管理员扩容。')
    return result


def counts(value):
    return {k:len(value[k]) for k in ('plans','records','reviews','reports','operations','claims')}


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class Preview(Input):
    code:str=Field(pattern=r'^[a-f0-9]{36}$')


class Confirm(Preview):
    preview_id:str=Field(min_length=8,max_length=80)
    consent:bool=False


def finish_import(source):
    with connection() as c:
        link,backup=state(c)
    if link.get('phase')=='active':return public(link)
    if link.get('snapshot_version')==2:
        from action_handoff_coordinator import finish_v2
        return finish_v2(source)
    if link.get('phase')!='pending' or not backup:fail(409,'没有待恢复的接管。')
    receipt=call(source,dict(action='import',snapshot=backup,snapshot_hash=link['snapshot_hash']))
    if not isinstance(receipt,dict) or receipt.get('snapshot_hash')!=link['snapshot_hash'] or receipt.get('source_counts')!=counts(backup) or receipt.get('binding_id')!=link['binding_id'] or receipt.get('target_user_id')!=link['target_user_id']:
        fail(503,'接管回执尚未通过核对，请重试；原始数据保持只读并保留备份。')
    with connection(True,allow_link=True) as c:
        current,_=state(c)
        if current.get('snapshot_hash')!=link['snapshot_hash']:fail(409,'接管状态已变化，请刷新。')
        current.update(phase='active',receipt=receipt);put(c,current)
    return public(current)


def public(link):
    return {'configured':bool(configuration()),'phase':link.get('phase','local'),'target_user_id':link.get('target_user_id'),'counts':link.get('counts'),'can_retry':link.get('phase')=='pending'}


def guard(request):
    if request.method not in ('GET','HEAD'):
        origin=f'{request.url.scheme}://{request.url.netloc}'
        if request.headers.get('X-Copilot-Request')!='1' or request.headers.get('Origin',origin)!=origin or request.headers.get('Sec-Fetch-Site')=='cross-site':fail(403,'需要同源请求。')
        length=request.headers.get('Content-Length','0')
        if not length.isdecimal() or int(length)>30000:fail(413,'请求内容过长。')


def register(app):
    router=APIRouter(prefix='/api/action-link')
    @router.get('')
    def status():
        identity()
        with connection() as c:link,_=state(c)
        return public(link)

    @router.get('/source-deliveries')
    def source_deliveries():
        identity()
        from action_source_delivery import list_deliveries
        return {'deliveries':list_deliveries()}

    @router.post('/source-deliveries/retry')
    def retry_sources():
        identity()
        from action_source_delivery import retry_due,list_deliveries
        retry_due(force=True,retry_blocked=True,limit=3)
        return {'deliveries':list_deliveries()}

    @router.post('/preview')
    def preview(body:Preview):
        source=identity()
        with connection() as c:
            from rhythm.store import has_data
            if has_data(c) or c.execute('SELECT count(*) FROM action_content_events').fetchone()[0] or any(json.loads(r[0]).get('schema_version')==2 for r in c.execute('SELECT data FROM action_plans')):
                fail(409,'P0接管合同尚待双端验证；计划继续保存在当前唯一写入方。','CONTRACT_UPGRADE_REQUIRED')
        target=call(source,{'action':'preview','code':body.code})
        with connection(True,allow_link=True) as c:
            current,_=state(c)
            if current.get('phase')!='local':fail(409,'这个账号已开始接管，请刷新连接状态。')
            data=snapshot(c);proposal=dict(preview_id=str(uuid.uuid4()),code_hash=fingerprint(body.code),snapshot_hash=fingerprint(data),target_user_id=target['target_user_id'],expires_at=target['expires_at'],counts=counts(data))
            put(c,{'phase':'local','preview':proposal})
        return {k:v for k,v in proposal.items() if k not in ('code_hash','snapshot_hash')}

    @router.post('/confirm')
    def confirm(body:Confirm):
        source=identity()
        if not body.consent:fail(422,'请先确认接管范围与目标账号。')
        with connection() as c:
            link,_=state(c);proposal=link.get('preview',{})
        if link.get('phase')=='active':return public(link)
        if link.get('phase')=='pending':return finish_import(source)
        if proposal.get('preview_id')!=body.preview_id or proposal.get('code_hash')!=fingerprint(body.code):fail(409,'请重新预览并确认连接。')
        with connection() as c:
            from rhythm.store import has_data
            if has_data(c):fail(409,'接管预览后新增了日常节奏数据，请等待连接端合同升级。','CONTRACT_UPGRADE_REQUIRED')
        target=call(source,dict(action='claim',code=body.code))
        if target['target_user_id']!=proposal['target_user_id']:fail(409,'目标账号已变化，请重新确认。')
        with connection(True,allow_link=True) as c:
            current,_=state(c)
            if current.get('phase')!='local':fail(409,'接管状态已变化，请刷新后重试。')
            data=snapshot(c)
            if fingerprint(data)!=proposal['snapshot_hash']:fail(409,'计划或执行已变化，请重新预览再确认。')
            if any(r.get('state')=='generating' for r in data['reports']):fail(409,'请等待正在生成的总结结束，再开始接管。')
            put(c,dict(phase='pending',binding_id=target['binding_id'],target_user_id=target['target_user_id'],snapshot_hash=fingerprint(data),counts=counts(data)),data)
        return finish_import(source)

    @router.post('/retry')
    def retry():return finish_import(identity())
    app.include_router(router)

    @app.middleware('http')
    async def forward(request:Request,call_next):
        path=request.url.path
        if not (path.startswith('/api/action-plans') or path.startswith('/api/action-link')):return await call_next(request)
        try:
            guard(request)
            if path.startswith('/api/action-link'):return await call_next(request)
            if request.method=='POST' and request.headers.get('X-Grow-Action-Schema')!='2':
                fail(409,'行动服务合同需升级。','CONTRACT_UPGRADE_REQUIRED')
            def read_state():
                with connection() as c:return state(c)[0]
            link=await run_in_threadpool(read_state)
            if path.startswith('/api/action-plans/rhythm/') and link.get('phase') != 'local':
                if request.method == 'GET' and path == '/api/action-plans/rhythm/capabilities':
                    from rhythm.contracts import rhythm_capability
                    return JSONResponse(rhythm_capability(link.get('phase')), headers={'Cache-Control':'no-store'})
                fail(409,'连接服务尚未支持日常节奏；不会读取旧数据或回落本地写入。','CONTRACT_UPGRADE_REQUIRED')
            if link.get('phase')=='local':return await call_next(request)
            source=identity()
            if request.method=='GET' and path.startswith('/api/action-plans/requests/'):
                key=path[len('/api/action-plans/requests/'):]
                if not key or len(key)>160:fail(422,'请求编号无效。')
                def local_receipt():
                    with connection() as c:
                        row=c.execute('SELECT result FROM action_operations WHERE key=?',(key,)).fetchone()
                        return {'found':True,'result':json.loads(row[0])} if row else None
                known=await run_in_threadpool(local_receipt)
                if known is not None:
                    return JSONResponse(known,headers={'Cache-Control':'no-store'})
                if link.get('phase')!='active':
                    fail(503,'接管尚未确认，未知请求的结果仍待核对，请保留原请求。')
                result=await run_in_threadpool(call,source,dict(action='request',method='GET',path='/requests/'+key,body={},query={}))
                if (not isinstance(result,dict) or type(result.get('found')) is not bool or 'result' not in result or
                    result['found'] and not isinstance(result['result'],dict) or not result['found'] and result['result'] is not None):
                    fail(503,'请求回执尚未通过核对，请保留原请求并重试。')
                return JSONResponse(result,headers={'Cache-Control':'no-store'})
            if link.get('phase')!='active':fail(503,'计划正在接管，请在 LightTick 联动中点击重试；已保留本地输入。')
            if request.method not in ('GET','POST'):fail(405,'请求方式无效。')
            if request.method=='POST':
                capability=await run_in_threadpool(call,source,dict(action='request',method='GET',path='',body={},query={}))
                caps=capability.get('capabilities',{}) if isinstance(capability,dict) else {}
                if (not isinstance(capability,dict) or capability.get('action_schema_version')!=2 or
                    not isinstance(caps,dict) or caps.get('connection_write_enabled') is not True or
                    caps.get('nullable_schedule') is not True or caps.get('actual_fact_dates') is not True or
                    not isinstance(caps.get('completion_modes'),list) or not all(mode in caps['completion_modes'] for mode in ('time','content','check')) or
                    not isinstance(caps.get('content_receipts'),list) or not all(kind in caps['content_receipts'] for kind in ('article','plan'))):
                    fail(409,'连接服务尚未支持P0，输入已保留，请等待合同升级。','CONTRACT_UPGRADE_REQUIRED')
            body=await request.json() if request.method=='POST' else {}
            result=await run_in_threadpool(call,source,dict(action='request',method=request.method,path=path[len('/api/action-plans'):],body=body,query=dict(request.query_params),**({'action_schema_version':2} if request.method=='POST' else {})))
            if path.endswith('/calendar.ics'):response=Response(result,media_type='text/calendar',headers={'Content-Disposition':'attachment; filename="grow-action.ics"'})
            else:response=JSONResponse(result)
            response.headers['Cache-Control']='no-store';return response
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc,HTTPException):return JSONResponse({'detail':exc.detail,**({'code':exc.code,**exc.extra} if hasattr(exc,'code') else {})},status_code=exc.status_code,headers={'Cache-Control':'no-store'})
            raise
