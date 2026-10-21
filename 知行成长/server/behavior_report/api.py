"""AI 行为分析报告 — API 路由。"""
from __future__ import annotations

import asyncio
from tenancy import scoped, runtime_root

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from copilot.ai_config import require_config

from .store import BehaviorReportStore
from .analyzer import generate_report_content


class Generation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ai_config: dict | None = Field(default=None, repr=False)


async def connected_generation(request, db_path, period_days, config):
    """Disconnecting cancels the provider stream before any report is saved."""
    if await request.is_disconnected():
        raise HTTPException(499, '生成已取消，未保存报告。')

    async def disconnected():
        while not await request.is_disconnected():
            await asyncio.sleep(.1)

    generation = asyncio.create_task(generate_report_content(db_path, period_days, config))
    disconnect = asyncio.create_task(disconnected())
    try:
        finished, _ = await asyncio.wait((generation, disconnect), return_when=asyncio.FIRST_COMPLETED)
        if disconnect in finished or await request.is_disconnected():
            raise HTTPException(499, '生成已取消，未保存报告。')
        return await generation
    finally:
        for task in (generation, disconnect):
            if not task.done():
                task.cancel()
        await asyncio.gather(generation, disconnect, return_exceptions=True)


def register(app: FastAPI, root, db_path) -> BehaviorReportStore:
    store = scoped(app, lambda: BehaviorReportStore(runtime_root(db_path)), initialize=True)

    def private(request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and (
                request.headers.get('X-Copilot-Request') != '1'
                or request.headers.get('Origin', origin) != origin
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise HTTPException(403, '生成和删除报告需要同源请求。')

    router = APIRouter(prefix="/api/behavior-report", dependencies=[Depends(private)])

    @router.post("/generate", status_code=201)
    async def generate_report(body: Generation, request: Request, period_days: int = 30):
        if period_days < 7 or period_days > 365:
            raise HTTPException(400, "period_days must be 7-365")

        config = require_config(body.ai_config)
        try:
            content, data_summary = await connected_generation(request, db_path, period_days, config)
        except HTTPException:
            raise
        except Exception:
            # Provider errors can contain credentials or raw response bodies.
            raise HTTPException(502, 'AI 报告生成失败，请核对 AI 配置和服务商状态后重试。') from None
        if await request.is_disconnected():
            raise HTTPException(499, '生成已取消，未保存报告。')
        try:
            from growth_statistics import shanghai_today
            return await run_in_threadpool(store.create_report,
                dt=shanghai_today().isoformat(),
                period_days=period_days,
                content=content,
                data_summary=data_summary,
            )
        except Exception:
            raise HTTPException(503, '报告保存失败，请稍后重试。') from None

    @router.get("")
    def list_reports():
        return store.list_reports()

    @router.get("/{report_id}")
    def get_report(report_id: int):
        row = store.get_report(report_id)
        if not row:
            raise HTTPException(404, "report not found")
        return row

    @router.delete("/{report_id}", status_code=204)
    def delete_report(report_id: int):
        if not store.delete_report(report_id):
            raise HTTPException(404, "report not found")

    app.include_router(router)
    return store
