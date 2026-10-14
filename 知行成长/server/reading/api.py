"""Local-only routes; model requests are always explicit."""
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from plans.api import Payload
from copilot.generation import availability,config
from copilot.core import fail
from .sources import FEEDS,TOPICS
from .store import ReadingStore
from .service import Reader

def public_job(j):
    if j.get('type')!='job':fail('not_found','阅读任务不存在。',404)
    return {k:v for k,v in j.items() if k not in ('context','request')}

def register(app,root,db):
    store=ReadingStore(root,db);reader=Reader(store);router=APIRouter(prefix='/api/reading')
    @app.middleware('http')
    async def protect(request:Request,call_next):
        if request.url.path.startswith('/api/reading'):
            if store.startup_error:return JSONResponse({'message':'认知阅读暂不可用，请核对磁盘与恢复记录。'},status_code=503)
            if request.method not in ('GET','HEAD','OPTIONS'):
                if request.headers.get('x-copilot-request')!='1':return JSONResponse({'message':'缺少同源写入标识。'},status_code=403)
                if int(request.headers.get('content-length','0'))>100000:return JSONResponse({'message':'内容过长。'},status_code=413)
        r=await call_next(request)
        if request.url.path.startswith('/api/reading'):r.headers['Cache-Control']='no-store'
        return r
    @router.get('')
    def listing():
        return {'preferences':store.prefs(),'sources':[{k:v for k,v in s.items() if k!='domains'} for s in FEEDS],
                'topics':list(TOPICS),'articles':sorted(store.articles(),key=lambda a:a['saved_at'],reverse=True),
                'jobs':[public_job(j) for j in sorted(store.jobs(),key=lambda x:x['created_at'],reverse=True)[:30]],
                'model':config(store)['model'],'unavailable':availability(store)}
    @router.post('/preferences')
    def prefs(body:Payload):return store.save_preferences(body.data)
    @router.post('/collect')
    async def collect(body:Payload):return public_job(reader.begin({**body.data,'kind':'collect'}))
    @router.get('/jobs/{jid}')
    def job(jid:str):return public_job(store.record(jid))
    @router.post('/jobs/{jid}/cancel')
    async def cancel(jid:str):return public_job(reader.cancel(jid))
    @router.post('/jobs/{jid}/save')
    def save(jid:str,body:Payload):return public_job(store.save_selection(jid,body.data.get('ids')))
    @router.get('/articles/{aid}')
    def article(aid:str):
        a=store.article(aid);rel=f'认知阅读/文章资料/{aid}/中文导读.md';file=store.path(rel)
        return {'article':a,'note':store.note(aid),'guide':file.read_text() if file.exists() else '导读文件缺失，请核对本地目录。','path':str(file)}
    @router.post('/articles/{aid}/personal')
    def personal(aid:str,body:Payload):return store.update_personal(aid,body.data)
    @router.post('/articles/{aid}/guide')
    async def guide(aid:str,body:Payload):return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'guide'}))
    app.include_router(router);return store,reader
