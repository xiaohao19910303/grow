"""Optional C05 consumer; canonical basic plans are never copied into Grow storage."""
import os
import re
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from copilot.core import fail
from zook_web_auth import enabled as identity_enabled, upstream
from zook_web_proxy import session


def enabled(): return identity_enabled() and os.getenv('GROW_NATIVE_BASIC_PLANS_ENABLED') == '1'


def install(app):
    router = APIRouter()

    @router.get('/api/native-plans/config')
    def config():
        from zook_web_auth import active
        return {'enabled': enabled(), 'unified': bool(active.get())}

    @router.get('/native-plans')
    def page():
        if not enabled(): fail('not_found', '此增强入口尚未开放。', 404)
        return FileResponse(Path(__file__).parent / 'static/native-basic-plans.html', headers={'Cache-Control': 'no-store'})

    @router.api_route('/api/native-plans/{path:path}', methods=['GET', 'POST', 'PATCH'])
    async def proxy(path: str, request: Request):
        if not enabled(): fail('native_plans_disabled', '网页增强暂不可用，App基础功能仍可继续。', 503)
        identifier = r'[a-zA-Z0-9_-]{1,128}'
        allowed = {
            'GET': rf'(?:goals|manual-plans|manual-plans/{identifier}|goals/{identifier}/continuation)',
            'POST': rf'(?:manual-plans|manual-plans/{identifier}/confirm)',
            'PATCH': rf'manual-plans/{identifier}',
        }
        if not re.fullmatch(allowed[request.method], path): fail('zook_proxy_forbidden', '此操作不在基础计划增强范围。', 403)
        if any(k not in ('period_start', 'period_end') for k in request.query_params): fail('zook_proxy_forbidden', '查询范围无效。', 422)
        body = None
        headers = {'X-LightTick-Task-Schema': '2'}
        if request.method != 'GET':
            key = request.headers.get('Idempotency-Key', '')
            if not re.fullmatch(r'[a-zA-Z0-9_.:-]{8,160}', key): fail('invalid_key', '请保留原提交请求后重试。', 422)
            headers['Idempotency-Key'] = key
            try: body = await request.json()
            except ValueError: fail('invalid_body', '请输入有效的计划内容。', 422)
            if not isinstance(body, dict): fail('invalid_body', '计划内容无效。', 422)
        # Bindings are checked by session(); the account middleware holds the identity lock on writes.
        def forward():
            value = session()
            return upstream('/api/v1/lighttick/' + path, request.method, body, value['token'], headers, dict(request.query_params))
        result = await run_in_threadpool(forward)
        return JSONResponse({'data': result}, headers={'Cache-Control': 'no-store'})

    app.include_router(router)
