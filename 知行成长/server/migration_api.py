"""Owner-only migration preview, hash-bound import and recovery of original modules."""
import json
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from copilot.core import fail
from legacy_files import preview, apply


class ImportToken(BaseModel):
    token: str = Field(min_length=64,max_length=64)


def register(app, course_store, root):
    router=APIRouter(prefix='/api/migrations')
    def store():
        try:
            from tenancy import current_user
            user=current_user.get()
        except ImportError:user=None
        if user and not user['is_owner']:fail('forbidden','仅原数据所有者可以执行旧数据迁移。',403)
        if not getattr(course_store,'remote',False):fail('cloud_required','请先启用 GitHub 内容存储。',409)
        return course_store
    def writer(request):
        if request.headers.get('x-copilot-request')!='1':fail('forbidden','缺少同源写入标识。',403)
    @router.get('')
    def status():
        current=store()
        with current.conn() as c:
            schemas=[json.loads(r[0]) for r in c.execute('SELECT data FROM platform_migrations')]
            imported=[{k:v for k,v in json.loads(r[0]).items() if k!='original_text'} for r in c.execute('SELECT data FROM cloud_file_imports')]
            review=[{'source_table':r[0],'source_key':r[1],'reason':r[2]} for r in c.execute("SELECT source_table,source_key,reason FROM legacy_row_map WHERE state='needs_review'")]
        pending=[{'id':key,'created_at':item['created_at']} for key,item in current.documents.rows('cloud_publications') if item['state']!='done']
        return {'schemas':schemas,'files':imported,'needs_review':review,'pending_publications':pending}
    @router.post('/files/preview')
    def preview_files(request:Request):
        writer(request);return preview(store().documents,root)
    @router.post('/files/apply')
    def apply_files(body:ImportToken,request:Request):
        writer(request);return apply(store().documents,root,body.token)
    @router.post('/recover')
    def recover(request:Request):
        writer(request);current=store()
        with current.lock():
            current.documents.recover()
            with current.conn() as c:keys=[r[0] for r in c.execute("SELECT id FROM copilot_operations WHERE status!='done'")]
            for key in keys:current._resume(key)
        return {'ok':True}
    app.include_router(router)
