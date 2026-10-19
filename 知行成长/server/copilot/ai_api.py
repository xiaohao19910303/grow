"""Browser AI configuration metadata and connectivity; no course store dependency."""
import asyncio
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .ai_config import require_config
from .core import Problem, fail


class ConnectionTest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_base_url: str
    api_key: str = Field(repr=False)
    model_name: str


def register(app):
    router = APIRouter()

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse({'error':error.code,'message':error.message},status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({'message':'请求字段格式无效，请检查填写内容。'},status_code=422)

    @router.get('/api/ai/settings')
    @router.get('/api/copilot/settings', include_in_schema=False)
    def settings():
        return {'storage':'browser','requires_own_config':True}

    @router.put('/api/copilot/settings', include_in_schema=False)
    def old_settings():
        fail('browser_config_only','AI 配置仅保存在浏览器，请刷新页面后在设置中保存。',410)

    @router.post('/api/ai/test')
    @router.post('/api/copilot/settings/test', include_in_schema=False)
    async def test(body: ConnectionTest, request: Request):
        if request.headers.get('x-copilot-request') != '1':
            fail('same_origin_required','连接测试需要同源请求标识。',403)
        cfg = require_config(body.model_dump())
        from .transport import qwen_stream
        try:
            collected = ''; complete = False
            async with asyncio.timeout(90):
                async for packet in qwen_stream([{'role':'user','content':'请只回复“连接成功”四个字。'}],cfg):
                    collected += packet.get('text','')
                    if len(collected)>512: raise ValueError('Unexpected connection test response size')
                    if packet.get('done'):
                        complete = True
                        break
            if complete and collected.strip():
                return {'ok':True,'message':'连接成功，模型正常响应','model':cfg['model']}
            return {'ok':False,'message':'连接失败：未收到完整的模型响应。'}
        except Exception:
            return {'ok':False,'message':'连接失败：请核对地址、密钥、模型和服务商状态。'}

    app.include_router(router)
