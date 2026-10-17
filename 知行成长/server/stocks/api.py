"""股票复盘路由：记录股票操作、追踪结果、复盘思考。"""
from tenancy import scoped, learning_root, runtime_root
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from copilot.core import fail, now
from .store import StockStore


class CreateStockPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stock_code: str = Field(max_length=20)
    stock_name: str = Field(max_length=100)
    action: str = Field(pattern='^(buy|sell|hold)$')
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    price: float = Field(ge=0)
    quantity: Optional[int] = Field(None, ge=0)
    rationale: str = Field(max_length=5000, default='')
    target_price: Optional[float] = Field(None, ge=0)
    stop_loss: Optional[float] = Field(None, ge=0)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    tags: list[str] = []


class UpdateStockPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stock_code: Optional[str] = Field(None, max_length=20)
    stock_name: Optional[str] = Field(None, max_length=100)
    action: Optional[str] = Field(None, pattern='^(buy|sell|hold)$')
    date: Optional[str] = Field(None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    price: Optional[float] = Field(None, ge=0)
    quantity: Optional[int] = Field(None, ge=0)
    rationale: Optional[str] = Field(None, max_length=5000)
    target_price: Optional[float] = Field(None, ge=0)
    stop_loss: Optional[float] = Field(None, ge=0)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    tags: Optional[list[str]] = None


class OutcomePayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: str = Field(pattern='^(success|failure)$')
    actual_price: float = Field(ge=0)
    result_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    retrospective: Optional[dict] = None


def register(app, root, db):
    store = scoped(app, lambda: StockStore(learning_root(root), runtime_root(db)), initialize=True)
    router = APIRouter(prefix='/api/stocks')

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if request.url.path.startswith('/api/stocks'):
            if store.startup_error:
                return JSONResponse({'message': '股票复盘暂不可用。'}, status_code=503)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                if request.headers.get('x-copilot-request') != '1':
                    return JSONResponse({'message': '缺少同源写入标识。'}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith('/api/stocks'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @router.get('')
    def listing(status: Optional[str] = None):
        records = store.list_records(status)
        stats = store.get_statistics()
        return {'records': records, 'statistics': stats}

    @router.get('/statistics')
    def statistics():
        return store.get_statistics()

    @router.post('')
    def create(body: CreateStockPayload):
        return store.create_record(body.model_dump())

    @router.get('/{record_id}')
    def detail(record_id: str):
        return store.get_record(record_id)

    @router.put('/{record_id}')
    def update(record_id: str, body: UpdateStockPayload):
        return store.update_record(record_id, body.model_dump(exclude_none=True))

    @router.post('/{record_id}/outcome')
    def outcome(record_id: str, body: OutcomePayload):
        return store.update_outcome(record_id, body.model_dump())

    @router.delete('/{record_id}')
    def delete(record_id: str):
        return store.delete_record(record_id)

    app.include_router(router)
    return store
