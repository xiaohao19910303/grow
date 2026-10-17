"""Local-only routes; model requests are always explicit."""
from tenancy import scoped, learning_root, runtime_root
import asyncio
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from plans.api import Payload
from copilot.generation import availability
from copilot.ai_config import require_config
from copilot.core import fail
from .sources import DEFAULT_FEEDS,TOPICS,fetch_article_content
from .store import ReadingStore
from .cloud_store import make_store
from .service import Reader

def public_job(j):
    if j.get('type')!='job':fail('not_found','阅读任务不存在。',404)
    return {k:v for k,v in j.items() if k not in ('context','request')}

def register(app,root,db):
    store=scoped(app, lambda: make_store(learning_root(root),runtime_root(db)), initialize=True);reader=scoped(app, lambda: Reader(store));router=APIRouter(prefix='/api/reading')
    @app.middleware('http')
    async def protect(request:Request,call_next):
        if request.url.path.startswith('/api/reading'):
            if store.startup_error:return JSONResponse({'message':'认知阅读暂不可用：文件与笔记尚未完成云端迁移。' if getattr(store.startup_error,'code','') == 'legacy_content_migration' else '认知阅读暂不可用，请核对磁盘与恢复记录。'},status_code=503)
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
                'storage_backend':'cloud' if getattr(store,'remote',False) else 'local',
                'sources':[{k:v for k,v in s.items() if k!='domains'} for s in all_sources],
                'default_sources':[{k:v for k,v in s.items() if k!='domains'} for s in DEFAULT_FEEDS],
                'custom_sources':[{k:v for k,v in s.items() if k!='domains'} for s in store.custom_sources()],
                'topics':list(TOPICS),
                'articles':sorted(articles,key=lambda a:a['saved_at'],reverse=True),
                'jobs':[public_job(j) for j in sorted(store.jobs(),key=lambda x:x['created_at'],reverse=True)[:30]],
                'requires_own_config':True,'unavailable':availability(store)}
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
        metadata=store.documents.metadata(rel) if getattr(store,'remote',False) else None
        return {'article':a,
                'reading_preferences':store.prefs(),
                'storage':'github' if metadata and metadata['storage']=='github' else 'local',
                'github_url':store.documents.content.url(rel,metadata['commit_sha']) if metadata and metadata['storage']=='github' else None,
                'commit_sha':metadata.get('commit_sha') if metadata else None,
                'note':store.note(aid),
                'guide':file.read_text() if file.exists() else None,
                'summary':summary_file.read_text() if summary_file.exists() else None,
                'english_learning':english_file.read_text() if english_file.exists() else None,
                'full_text':a.get('full_content') if a.get('content_version')==2 else (full_text_file.read_text() if full_text_file.exists() else a.get('full_content')),
                'content_needs_refresh':a.get('content_version') != 2 and a.get('import_method') not in ('paste','url'),
                'content_job':next((public_job(j) for j in sorted(store.jobs(),key=lambda j:j['created_at'],reverse=True)
                                    if j.get('kind')=='fetch_full' and (j.get('context') or {}).get('article_id')==aid),None),
                'path':str(file)}
    @router.post('/articles/{aid}/personal')
    def personal(aid:str,body:Payload):return store.update_personal(aid,body.data)
    @router.post('/articles/{aid}/feedback')
    def feedback(aid:str,body:Payload):return store.save_feedback(aid,body.data)
    @router.post('/articles/{aid}/guide')
    async def guide(aid:str,body:Payload):
        require_config(body.data.get('ai_config'))
        return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'guide','guide_format':body.data.get('guide_format'),'ai_config':body.data.get('ai_config')}))
    @router.post('/articles/{aid}/summary')
    async def summary(aid:str,body:Payload):
        require_config(body.data.get('ai_config'))
        return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'summary','ai_config':body.data.get('ai_config')}))
    @router.post('/articles/{aid}/english')
    async def english(aid:str,body:Payload):
        require_config(body.data.get('ai_config'))
        return public_job(reader.begin({'key':body.data.get('key'),'article_id':aid,'kind':'english','ai_config':body.data.get('ai_config')}))
    @router.post('/articles/{aid}/fetch_full')
    async def fetch_full(aid:str,body:Payload,background:BackgroundTasks):
        job,created=await asyncio.to_thread(reader.begin,{'key':body.data.get('key'),'article_id':aid,'kind':'fetch_full'},defer=True)
        if created:
            async def launch():reader.launch(job['id'])
            background.add_task(launch)
        return public_job(job)
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
    # Phase 2: translation drafts
    @router.get('/articles/{aid}/translation')
    def get_translation(aid:str,paragraph_id:str=None):return store.get_translation_draft(aid,paragraph_id)
    @router.post('/articles/{aid}/translation')
    def save_translation(aid:str,body:Payload):
        pid=body.data.get('paragraph_id')
        text=body.data.get('text','')
        if not pid:fail('invalid','缺少段落编号。',422)
        return store.save_translation_draft(aid,pid,text,body.data.get('version'))
    @router.post('/articles/{aid}/translation/adopt')
    def adopt_translation(aid:str,body:Payload):
        pid=body.data.get('paragraph_id')
        if not pid:fail('invalid','缺少段落编号。',422)
        return store.adopt_translation(aid,pid)
    # Phase 2: summary/english drafts
    @router.post('/articles/{aid}/summary-draft')
    def save_summary_draft(aid:str,body:Payload):return store.save_summary_draft(aid,body.data.get('text',''),body.data.get('version'))
    @router.post('/articles/{aid}/summary-draft/adopt')
    def adopt_summary_draft(aid:str):return store.adopt_summary(aid)
    @router.post('/articles/{aid}/english-draft')
    def save_english_draft(aid:str,body:Payload):return store.save_english_draft(aid,body.data.get('text',''),body.data.get('version'))
    @router.post('/articles/{aid}/english-draft/adopt')
    def adopt_english_draft(aid:str):return store.adopt_english(aid)
    # Phase 2: vocabulary
    @router.get('/vocabulary')
    def list_vocab(article_id:str=None,include_archived:bool=False,include_paused:bool=True):return store.list_vocabulary(article_id,include_archived,include_paused)
    @router.get('/vocabulary/due')
    def due_vocab(article_id:str=None):return store.get_due_vocabulary(article_id)
    @router.get('/vocabulary/stats')
    def vocab_stats(article_id:str=None):return store.get_vocabulary_stats(article_id)
    @router.post('/vocabulary')
    def add_vocab(body:Payload):
        aid=body.data.get('article_id')
        word=body.data.get('word','')
        if not aid or not word:fail('invalid','缺少必填字段。',422)
        return store.add_vocabulary(aid,word,context_sentence=body.data.get('context_sentence'),contextual_meaning=body.data.get('contextual_meaning'),part_of_speech=body.data.get('part_of_speech'),pronunciation=body.data.get('pronunciation'),source_version=body.data.get('source_version',1))
    @router.get('/vocabulary/{vid}')
    def get_vocab(vid:str):return store.get_vocabulary(vid)
    @router.post('/vocabulary/{vid}/review')
    def review_vocab(vid:str,body:Payload):return store.review_vocabulary(vid,body.data.get('feedback',''))
    @router.post('/vocabulary/{vid}/pause')
    def pause_vocab(vid:str,body:Payload):return store.pause_vocabulary(vid,body.data.get('paused',True))
    @router.post('/vocabulary/{vid}/archive')
    def archive_vocab(vid:str,body:Payload):return store.archive_vocabulary(vid,body.data.get('archived',True))
    @router.delete('/vocabulary/{vid}')
    def delete_vocab(vid:str):return store.delete_vocabulary(vid)
    from .scheduled import register as register_scheduled
    register_scheduled(router,store,reader)
    app.include_router(router);return store,reader
