"""日常复盘路由：低门槛记录、独立保存、按需 AI 辅助。"""
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from copilot.core import fail, now
from copilot.generation import availability, config
from .store import ReflectionsStore
from .assist import ReflectionAssistant


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    data: dict


class CreatePayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    record_date: str
    prompt_kind: str = '自由记录'
    raw_text: str = Field(max_length=10000)
    guided_answers: dict = {}
    tags: list[str] = []
    key: str = Field(min_length=8, max_length=160)


class UpdatePayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_version: int = Field(ge=1)
    record_date: str
    prompt_kind: str = '自由记录'
    raw_text: str = Field(max_length=10000)
    guided_answers: dict = {}
    tags: list[str] = []
    key: str = Field(min_length=8, max_length=160)


class AssistPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    snapshot: dict
    key: str = Field(min_length=8, max_length=160)


class AdoptPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    attempt_key: str = Field(min_length=8, max_length=160)
    key: str = Field(min_length=8, max_length=160)


def register(app, root, db):
    store = ReflectionsStore(root, db)
    assistant = ReflectionAssistant(store)
    router = APIRouter(prefix='/api/reflections')

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if request.url.path.startswith('/api/reflections'):
            if store.startup_error:
                return JSONResponse({'message': '日常记录暂不可用，请核对磁盘与恢复日志。'}, status_code=503)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                if request.headers.get('x-copilot-request') != '1':
                    return JSONResponse({'message': '缺少同源写入标识。'}, status_code=403)
                if int(request.headers.get('content-length', '0')) > 400000:
                    return JSONResponse({'message': '请求内容过长。'}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith('/api/reflections'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @router.get('')
    def listing(include_archived: bool = False):
        entries = store.list_entries(include_archived)
        return {'entries': entries, 'generation_unavailable': availability(store),
                'model': config(store)['model']}

    @router.get('/export')
    def export(include_archived: bool = False):
        entries = store.list_entries(include_archived)
        return {'entries': entries, 'generated_at': now()}

    @router.post('')
    def create(body: CreatePayload):
        return store.create(body.model_dump(), body.key)

    @router.get('/{entry_id}')
    def detail(entry_id: str):
        entry = store.entry(entry_id)
        return {'entry': entry, 'versions': store.versions(entry_id),
                'attempts': assistant.attempts(entry_id)}

    @router.put('/{entry_id}')
    def update(entry_id: str, body: UpdatePayload):
        return store.update(entry_id, body.model_dump(), body.key)

    @router.get('/{entry_id}/versions')
    def versions(entry_id: str):
        return {'versions': store.versions(entry_id)}

    @router.post('/{entry_id}/archive')
    def archive(entry_id: str, body: Payload):
        return store.archive(entry_id, body.data.get('key', ''))

    @router.post('/{entry_id}/restore')
    def restore(entry_id: str, body: Payload):
        return store.restore(entry_id, body.data.get('key', ''))

    @router.post('/{entry_id}/assist')
    async def assist(entry_id: str, body: AssistPayload):
        return assistant.begin(entry_id, body.kind, body.snapshot, body.key)

    @router.get('/attempts/{attempt_key}')
    def attempt(attempt_key: str):
        return assistant.attempt(attempt_key)

    @router.post('/attempts/{attempt_key}/cancel')
    async def cancel(attempt_key: str):
        return assistant.cancel(attempt_key)

    @router.post('/attempts/{attempt_key}/answers')
    def save_answers(attempt_key: str, body: Payload):
        return assistant.save_answers(attempt_key, body.data.get('answers', []))

    @router.post('/{entry_id}/adopt')
    def adopt(entry_id: str, body: AdoptPayload):
        return store.adopt(entry_id, body.attempt_key, body.key)

    app.include_router(router)
    return store, assistant