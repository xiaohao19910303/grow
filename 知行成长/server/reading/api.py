"""Local-only routes; model requests are always explicit."""
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from plans.api import Payload
from copilot.generation import availability,config
from copilot.core import fail
from .sources import DEFAULT_FEEDS,TOPICS,fetch_article_content
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
    def listing(search:str=None,include_archived:bool=False):
        all_sources = store.all_sources()
        articles = store.search_articles(search, include_archived) if search else store.articles(include_archived=include_archived)
        return {'preferences':store.prefs(),
                'sources':[{k:v for k,v in s.items() if k!='domains'} for s in all_sources],
                'default_sources':[{k:v for k,v in s.items() if k!='domains'} for s in DEFAULT_FEEDS],
                'custom_sources':[{k:v for k,v in s.items() if k!='domains'} for s in store.custom_sources()],
                'topics':list(TOPICS),
                'articles':sorted(articles,key=lambda a:a['saved_at'],reverse=True),
                'jobs':[public_job(j) for j in sorted(store.jobs(),key=lambda x:x['created_at'],reverse=True)[:30]],
                'model':config(store)['model'],'unavailable':availability(store)}
    @router.post('/preferences')
    def prefs(body:Payload):return store.save_preferences(body.data)
    @router.post('/sources')
    def add_source(body:Payload):return store.add_custom_source(body.data)
    @router.delete('/sources/{sid}')
    def remove_source(sid:str):return store.remove_custom_source(sid)
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
        summary_file=store.path(f'认知阅读/文章资料/{aid}/详细总结.md')
        english_file=store.path(f'认知阅读/文章资料/{aid}/英语学习.md')
        full_text_file=store.path(f'认知阅读/文章资料/{aid}/原文.md')
        return {'article':a,
                'note':store.note(aid),
                'guide':file.read_text() if file.exists() else None,
                'summary':summary_file.read_text() if summary_file.exists() else None,
                'english_learning':english_file.read_text() if english_file.exists() else None,
                'full_text':full_text_file.read_text() if full_text_file.exists() else None,
                'path':str(file)}
    @router.post('/articles/{aid}/personal')
    def personal(aid:str,body:Payload):return store.update_personal(aid,body.data)
    @router.post('/articles/{aid}/guide')
    async def guide(aid:str,body:Payload):return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'guide'}))
    @router.post('/articles/{aid}/summary')
    async def summary(aid:str,body:Payload):return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'summary'}))
    @router.post('/articles/{aid}/english')
    async def english(aid:str,body:Payload):return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'english'}))
    @router.post('/articles/{aid}/fetch_full')
    async def fetch_full(aid:str,body:Payload):return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'fetch_full'}))
    @router.post('/import-url')
    async def import_url(body:Payload):
        url=body.data.get('url','').strip()
        if not url or not url.startswith(('http://','https://')):
            fail('invalid','请输入有效的 URL（http/https）。',422)
        content=await fetch_article_content(url)
        if not content or len(content)<50:
            return {'status':'preview','url':url,'content':None,'warning':'未能获取到有效正文，请检查链接或手动粘贴正文。'}
        title=body.data.get('title','').strip()
        author=body.data.get('author','').strip()
        language=body.data.get('language','zh')
        tags=body.data.get('tags',[])
        if body.data.get('confirm'):
            article=store.import_from_url(url,content,title=title or '未命名文章',author=author,language=language,tags=tags)
            return {'status':'saved','article':article}
        return {'status':'preview','url':url,'content':content[:2000],'title':title,'author':author,'language':language,'tags':tags}
    @router.post('/import-paste')
    async def import_paste(body:Payload):
        title=body.data.get('title','').strip()
        content=body.data.get('content','').strip()
        author=body.data.get('author','').strip()
        language=body.data.get('language','zh')
        tags=body.data.get('tags',[])
        url=body.data.get('url','').strip() or None
        article=store.import_from_paste(title,content,author=author,language=language,tags=tags,url=url)
        return {'status':'saved','article':article}
    @router.post('/articles/{aid}/archive')
    def archive(aid:str):return store.archive_article(aid)
    @router.post('/articles/{aid}/restore')
    def restore(aid:str):return store.restore_article(aid)
    app.include_router(router);return store,reader
