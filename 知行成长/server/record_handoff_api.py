"""Source UI compatibility adapter after records acquire one canonical writer."""
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field
from copilot.core import fail,Problem
from record_handoff import call,state,public,configuration,preview,confirm,finish,digest,KINDS,cancel

class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(pattern=r'^[a-f0-9]{36}$')
class Confirm(Preview):
    preview_id:str=Field(min_length=8,max_length=80)
    consent:bool=False
class Retry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str|None=Field(default=None,pattern=r'^[a-f0-9]{36}$')

def register(app,store):
    router=APIRouter(prefix='/api/record-link')
    @router.get('')
    def status():
        value=state(store);result={**public(value),'configured':bool(configuration())}
        if value['phase']=='active':result['phase']=call({'action':'status'})['phase']
        return result
    @router.post('/preview')
    def propose(body:Preview):return preview(store,body.code)
    @router.post('/confirm')
    def accept(body:Confirm):return confirm(store,body.code,body.preview_id,body.consent)
    @router.post('/retry')
    def retry(body:Retry):return finish(store,body.code)
    @router.post('/cancel')
    def abort():return cancel(store)
    @router.get('/export')
    def export():
        if state(store)['phase']!='active':fail('not_active','记录尚未完成联动。')
        return call({'action':'request','method':'GET','path':'export'})
    app.include_router(router)

def legacy(record,history=None):
    result={**record,'prompt_kind':{v:k for k,v in KINDS.items()}.get(record['prompt_kind'],record['prompt_kind']),'status':'recorded','path':None,'entry_id':record['id']}
    if record.get('adopted_summary'):
        original=(history or {}).get('private_history',{}).get('entry',{}).get('adopted_summary')
        result['adopted_summary']=original if original and record.get('adopted_summary')=='\n\n'.join(s.get('text','') for s in original.get('sections',[])) else {'sections':[{'kind':'event','text':record['adopted_summary'],'basis':'statement'}]}
        result['status']='organized' if record.get('summary_basis_version')==record['version']-1 else 'basis_updated'
    return result

def remote(path,method='GET',**fields):return call({'action':'request','path':path,'method':method,**fields})

def proxy(store,path,method,query,body):
    phase=state(store)['phase']
    if phase in ('local','preview'):return None
    if phase!='active':fail('records_frozen','记录交接尚未确认，请在设置中重试恢复；当前输入保留。',423)
    suffix=path[len('/api/reflections'):].strip('/')
    if method=='GET':
        if suffix=='export':
            value=remote('export');return {**value,'entries':[legacy(e['record'],e.get('source_history')) for e in value['records']],'generated_at':value['exported_at']}
        if suffix.startswith('attempts/'):return remote('attempt',id=suffix.split('/')[1])
        if not suffix:
            entries=[];cursor=None
            while True:
                page=remote('list',query={'archived':'all' if query.get('include_archived')=='true' else 'false','limit':'200',**({'cursor':cursor} if cursor else {})})
                entries.extend(legacy(e) for e in page['items']);cursor=page.get('next_cursor')
                if not cursor:break
            return {'entries':entries,'generation_unavailable':'已接管记录支持跨端编辑；历史 AI 建议可查看，本阶段暂不新增生成。','requires_own_config':False,'storage':'lighttick'}
        parts=suffix.split('/');detail=remote('detail',id=parts[0]);entry=legacy(detail['record'],detail.get('source_history'))
        if len(parts)==1:return {'entry':entry,'versions':[legacy(v) for v in detail['versions']],'attempts':(detail.get('source_history') or {}).get('private_history',{}).get('attempts',[])}
        if parts[1]=='versions':return {'versions':[legacy(v) for v in detail['versions']]}
        if parts[1]=='file-status':
            from reflections.store import render_markdown
            return {'id':entry['id'],'storage':'lighttick','path':None,'conflict':False,'saved_markdown':render_markdown(entry),'file_markdown':None}
    if method in ('POST','PUT'):
        parts=suffix.split('/') if suffix else [];action=parts[1] if len(parts)>1 else 'save'
        if action not in ('save','archive','restore'):fail('ai_history_only','本阶段保留 AI 历史只读，请先保存原文。',409)
        key=body.get('key') or (body.get('data') or {}).get('key')
        if not isinstance(key,str) or not 8<=len(key)<=160:fail('invalid','缺少有效请求标识。',422)
        from record_handoff import identity
        entry_id=parts[0] if parts else 'web-'+digest({'source':identity(),'key':key})
        current=remote('detail',id=entry_id)['record'] if parts else None
        payload={'base_version':body.get('base_version',current['version'] if current else 0)}
        if action=='save':
            payload.update({k:body.get(k,{} if k=='guided_answers' else [] if k=='tags' else '') for k in ('raw_text','record_date','guided_answers','tags')})
            payload['prompt_kind']=KINDS.get(body.get('prompt_kind','自由记录'),body.get('prompt_kind'))
            if current and current.get('adopted_summary') is not None:payload.update({k:current[k] for k in ('adopted_summary','summary_basis_version')})
        saved=remote(action,'PUT' if action=='save' else 'POST',id=entry_id,key='grow-web-'+digest(key),body=payload)
        return {'id':saved['id'],'version':saved['version'],'archived':bool(saved.get('archived_at'))}
    fail('not_found','记录接口不存在。',404)
