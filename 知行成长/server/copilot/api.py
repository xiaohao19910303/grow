"""Additive API routes; construction does not open the database or start a service."""
import json
import secrets
import os
from typing import Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .core import Problem, Store
from .generation import Generator, availability
from .backup import snapshot


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    module: Literal['renzhi'] = 'renzhi'


class Key(Input):
    key: str = Field(min_length=8, max_length=160)


class Generation(Key):
    lesson_no: int = Field(ge=1, le=168)


class Edit(Input):
    version: int = Field(ge=1)
    content: str = Field(max_length=100000)
    sources: str = Field(max_length=100000)


class Publication(Key):
    draft_id: str = Field(max_length=64)
    version: int = Field(ge=1)


class Learning(Key):
    state: Literal['completed', 'unknown']
    version: str = Field(min_length=64, max_length=64)


class ReviewSubmission(Key):
    answers: list[dict] = Field(min_length=1, max_length=10)
    time_spent_seconds: int = Field(ge=0)
    version: str = Field(min_length=64, max_length=64)


class SummarySubmission(Key):
    summary: str = Field(min_length=1, max_length=1000)
    time_spent_seconds: int = Field(ge=0)
    version: str = Field(min_length=64, max_length=64)


class QuickCompletion(Key):
    time_spent_seconds: int = Field(ge=0)
    version: str = Field(min_length=64, max_length=64)


class FeedbackSubmission(Key):
    mastery_level: Literal['fully_understood', 'basically_understood', 'partially_understood', 'not_understood']
    value_rating: int = Field(ge=0, le=3)
    feeling_tags: list[str] = Field(default=[], max_length=10)
    key_learnings: str = Field(default='', max_length=2000)
    questions: str = Field(default='', max_length=2000)
    next_direction: str = Field(default='', max_length=1000)


class SummaryGeneration(Input):
    scope: Literal['full_course', 'single_lesson'] = 'full_course'


class ArchiveRequest(Key):
    pass


class PlanConfirmation(Input):
    hash: str = Field(min_length=64, max_length=64)
    lessons: list[int] = Field(min_length=1, max_length=168)


class WriterConfirmation(Input):
    confirmed: Literal[True]


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_base_url: str = ''
    api_key: str = ''
    model_name: str = 'qwen-plus'
    price_version: str = ''
    input_price: str = ''
    output_price: str = ''


class ConnectionTest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=100)


def register(app: FastAPI, root, db):
    store = Store(root, db)
    generator = Generator(store)
    router = APIRouter(prefix='/api/copilot')

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({'error': error.code, 'message': error.message}, status_code=error.status)

    @app.middleware('http')
    async def local_access(request: Request, call_next):
        hostname = request.url.hostname or ''
        allowed = {'localhost', '127.0.0.1', '::1'}
        lan_hosts = {h.strip() for h in os.getenv('COPILOT_ALLOWED_HOSTS', '').split(',') if h.strip()}
        lan_token = os.getenv('COPILOT_ACCESS_TOKEN', '')
        lan = os.getenv('COPILOT_LAN', '') == '1'
        if hostname not in allowed and not (lan and hostname in lan_hosts and len(lan_token) >= 24):
            return JSONResponse({'message': '此访问地址未获允许。'}, status_code=403)
        if request.url.path.startswith('/api/'):
            peer = request.client.host if request.client else ''
            if peer not in ('127.0.0.1', '::1', 'testclient'):
                supplied = request.headers.get('x-copilot-token', '')
                if not lan or len(lan_token) < 24 or not secrets.compare_digest(supplied, lan_token):
                    return JSONResponse({'message': '局域网访问需要有效凭证。'}, status_code=403)
            origin = request.headers.get('origin')
            expected = f'{request.url.scheme}://{request.url.netloc}'
            if origin and origin != expected:
                return JSONResponse({'message': '拒绝跨来源请求。'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'message': '拒绝跨站请求。'}, status_code=403)
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith('/api/copilot'):
                if request.headers.get('x-copilot-request') != '1':
                    return JSONResponse({'message': '写操作需要同源请求标识。'}, status_code=403)
            if (store.runtime / 'restore-pending.json').exists():
                return JSONResponse({'message': '存在未完成的离线恢复，请先按备份说明处理。'}, status_code=503)
        if request.url.path.startswith('/api/copilot') and getattr(store, 'startup_error', None):
            error = store.startup_error
            return JSONResponse({'error': error.code, 'message': error.message + ' 处理后请重新启动本地服务。'}, status_code=503)
        response = await call_next(request)
        if request.url.path.startswith('/api/copilot'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @router.get('/today-task')
    def today_task(module: Literal['renzhi'] = 'renzhi'):
        with store.lock():
            data, plan, sources, blockers = store.readiness()
        unavailable = availability(store)
        return {**data, 'blockers': blockers, 'plan': plan, 'generation_unavailable': unavailable,
                'can_generate': not blockers and not unavailable, 'writer_coordinated': store.coordinated()}

    @router.post('/scan')
    def scan(body: Input):
        return store.scan()

    @router.get('/lessons')
    def lessons(module: Literal['renzhi'] = 'renzhi', state: Literal['all', 'unknown', 'completed'] = 'all',
                offset: int = 0, limit: int = 30):
        data = store.scan()['lessons']
        data = [x for x in data if state == 'all' or x['learning_state'] == state]
        offset, limit = max(0, offset), min(168, max(1, limit))
        return {'total': len(data), 'items': data[offset:offset + limit]}

    @router.get('/lessons/{number}')
    def lesson(number: int, module: Literal['renzhi'] = 'renzhi'):
        return store.lesson(number)

    @router.patch('/lessons/{number}/learning-state')
    def learning(number: int, body: Learning):
        return store.learning(number, body.state, body.version, body.key)

    @router.post('/lessons/{number}/review')
    def submit_review(number: int, body: ReviewSubmission):
        return store.submit_review(number, body.answers, body.time_spent_seconds, body.version, body.key)

    @router.post('/lessons/{number}/summary')
    def submit_summary(number: int, body: SummarySubmission):
        return store.submit_summary(number, body.summary, body.time_spent_seconds, body.version, body.key)

    @router.post('/lessons/{number}/complete')
    def quick_complete(number: int, body: QuickCompletion):
        return store.quick_complete(number, body.time_spent_seconds, body.version, body.key)

    @router.get('/lessons/{number}/learning-record')
    def learning_record(number: int, module: Literal['renzhi'] = 'renzhi'):
        return store.get_learning_record(number)

    @router.get('/lessons/{number}/review-questions')
    def review_questions(number: int, module: Literal['renzhi'] = 'renzhi'):
        questions = store.extract_review_questions(number)
        if not questions:
            return {'questions': []}
        return {'questions': questions}

    @router.post('/lessons/{number}/feedback')
    def submit_feedback(number: int, body: FeedbackSubmission):
        return store.save_feedback(number, body.model_dump(), body.key)

    @router.get('/lessons/{number}/feedback')
    def get_feedback(number: int, module: Literal['renzhi'] = 'renzhi'):
        result = store.get_feedback(number)
        if not result:
            return JSONResponse({'error': 'not_found', 'message': '未找到反馈记录。'}, status_code=404)
        return result

    @router.post('/lessons/{number}/archive')
    def archive(number: int, body: ArchiveRequest):
        return store.archive_lesson(number, body.key)

    @router.post('/lessons/{number}/unarchive')
    def unarchive(number: int, body: ArchiveRequest):
        return store.unarchive_lesson(number, body.key)

    @router.get('/lessons/archived')
    def archived_lessons(module: Literal['renzhi'] = 'renzhi'):
        return {'items': store.list_archived()}

    @router.post('/summaries/generate')
    def generate_summary(body: SummaryGeneration):
        from .summary import SummaryGenerator
        gen = SummaryGenerator(store)
        round_id = 1
        if hasattr(body, 'round_id'):
            round_id = body.round_id
        return StreamingResponse(gen.generate(body.module, round_id, body.scope),
                                 media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @router.get('/summaries')
    def summaries(module: Literal['renzhi'] = 'renzhi'):
        return {'items': store.list_summaries(module)}

    @router.get('/summaries/{summary_id}')
    def summary(summary_id: int, module: Literal['renzhi'] = 'renzhi'):
        return store.get_summary(summary_id)

    @router.get('/learning-history/by-date')
    def learning_history_by_date(date: str, module: Literal['renzhi'] = 'renzhi'):
        """Get learning history for a specific date."""
        # date format: YYYY-MM-DD
        return store.get_learning_history_by_date(module, date)

    @router.get('/learning-history/months')
    def learning_history_months(start: str, end: str, module: Literal['renzhi'] = 'renzhi'):
        """Get learning records for a date range (for calendar view)."""
        # start/end format: YYYY-MM-DD
        return store.get_learning_history_months(module, start, end)

    @router.get('/learning-history')
    def learning_history(module: Literal['renzhi'] = 'renzhi', offset: int = 0, limit: int = 20):
        return store.get_learning_history(offset, limit)

    @router.get('/plan')
    def plan(module: Literal['renzhi'] = 'renzhi'):
        return store.plan()

    @router.post('/plan/confirm')
    def confirm_plan(body: PlanConfirmation):
        return store.confirm_plan(body.hash, body.lessons)

    @router.post('/writer-session')
    def writer_session(body: WriterConfirmation):
        return store.writer_session(body.confirmed)

    @router.post('/generations')
    def generate(body: Generation):
        draft_id, fresh = generator.begin(body.lesson_no, body.key)
        return StreamingResponse(generator.stream(draft_id, fresh), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @router.post('/generations/{draft_id}/cancel')
    async def cancel(draft_id: str, body: Input):
        return generator.cancel(draft_id)

    @router.get('/drafts')
    def drafts(module: Literal['renzhi'] = 'renzhi'):
        with store.conn() as c:
            items = [dict(row) for row in c.execute(
                'SELECT id,lesson_no,version,status,updated_at FROM copilot_drafts ORDER BY updated_at DESC LIMIT 50')]
        return {'items': items}

    @router.get('/drafts/{draft_id}')
    def draft(draft_id: str, module: Literal['renzhi'] = 'renzhi'):
        return store.draft(draft_id)

    @router.patch('/drafts/{draft_id}')
    def edit(draft_id: str, body: Edit):
        return store.edit_draft(draft_id, body.version, body.content, body.sources)

    @router.post('/publications')
    def publish(body: Publication):
        return store.publish(body.draft_id, body.version, body.key)

    @router.get('/operations')
    def operations(module: Literal['renzhi'] = 'renzhi'):
        with store.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT id,status,created_at,data FROM copilot_operations WHERE status!='done' ORDER BY created_at")]
        for row in rows:
            row['error'] = json.loads(row.pop('data')).get('error', '')
        return {'items': rows}

    @router.get('/operations/{op_id}')
    def operation(op_id: str):
        op = store.operation(op_id)
        return {'id': op['id'], 'status': op['status'], 'created_at': op['created_at'], 'error': json.loads(op['data']).get('error', '')}

    @router.post('/operations/{op_id}/recover')
    def recover(op_id: str, body: Input):
        return store.recover(op_id)

    @router.post('/backups')
    def backup(body: Input):
        with store.lock():
            store.require_writer()
            return snapshot(store)

    @router.get('/settings')
    def get_settings():
        keys = ('api_base_url', 'api_key', 'model_name', 'price_version', 'input_price', 'output_price')
        result = {}
        for k in keys:
            v = store.get_setting(k)
            if k == 'api_key' and v:
                result[k] = v[:4] + '****' + v[-4:] if len(v) > 8 else '****'
            else:
                result[k] = v
        return {**result, 'generation_available': not availability(store)}

    @router.put('/settings')
    def update_settings(body: SettingsUpdate):
        with store.lock():
            store.require_writer()
            store.update_settings({k: v for k, v in body.model_dump().items() if v})
        return {'ok': True, 'generation_available': not availability(store)}

    @router.post('/settings/test')
    async def test_connection(body: ConnectionTest):
        from .transport import qwen_stream
        import asyncio
        test_messages = [{'role': 'user', 'content': '请回复"连接成功"四个字'}]
        test_config = {'url': body.api_base_url, 'key': body.api_key, 'model': body.model_name}
        try:
            collected = ''
            async for packet in qwen_stream(test_messages, test_config):
                if packet.get('done'):
                    break
                if packet.get('text'):
                    collected += packet['text']
                    if len(collected) > 100:
                        break
            if collected:
                return {'ok': True, 'message': f'连接成功，模型 {body.model_name} 正常响应'}
            return {'ok': False, 'message': '连接失败：未收到有效响应'}
        except Exception as e:
            return {'ok': False, 'message': f'连接失败：{str(e)[:100]}'}

    app.include_router(router)
    return store
