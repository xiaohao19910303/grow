"""AI 行为分析报告 — API 路由。"""
from __future__ import annotations

import asyncio
import uuid
from tenancy import scoped, runtime_root

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from copilot.ai_config import require_config

from .store import BehaviorReportStore


class Generation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ai_config: dict | None = Field(default=None, repr=False)


class JobGeneration(Generation):
    key: str = Field(min_length=8, max_length=160)
    period_days: int = Field(default=30, ge=7, le=365, strict=True)
    retry_of: str | None = Field(default=None, max_length=100)


async def connected_generation(request, store, period_days, ai_config):
    """旧同步接口观察同一个后台服务；断线仍明确取消，不创建第二份报告。"""
    if await request.is_disconnected():
        raise HTTPException(499, '生成已取消，未保存报告。')
    commit_gate=asyncio.Event()
    submission=asyncio.create_task(store.jobs.submit('legacy-' + uuid.uuid4().hex, period_days, ai_config, deduplicate=False, commit_gate=commit_gate))
    try:job=await asyncio.shield(submission)
    except asyncio.CancelledError:
        job=await submission
        await asyncio.shield(store.jobs.cancel(job['id']))
        raise
    try:
        while True:
            if await request.is_disconnected():
                await store.jobs.cancel(job['id'])
                raise HTTPException(499, '生成已取消，未保存报告。')
            current = await run_in_threadpool(store.jobs.get, job['id'])
            if current.get('awaiting_confirmation') and current['state'] in ('queued','generating'):commit_gate.set()
            if current['state'] == 'ready':
                return await run_in_threadpool(store.get_report, current['result_id'])
            if current['state'] not in ('queued', 'generating'):
                raise HTTPException(502, current.get('error') or '报告生成失败。')
            await asyncio.sleep(.05)
    except asyncio.CancelledError:
        await asyncio.shield(store.jobs.cancel(job['id']))
        raise


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

        require_config(body.ai_config)
        return await connected_generation(request, store, period_days, body.ai_config)

    @router.post('/jobs', status_code=202)
    async def create_job(body: JobGeneration):
        return await asyncio.shield(store.jobs.submit(body.key, body.period_days, body.ai_config, body.retry_of))

    @router.get('/jobs')
    def jobs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        return store.jobs.listing(page, page_size)

    @router.get('/jobs/{job_id}')
    def job(job_id: str):
        return store.jobs.get(job_id)

    @router.get('/jobs/by-request/{request_key}')
    def by_request(request_key: str):
        with store.conn() as c:
            row=c.execute('SELECT job_id FROM behavior_report_requests WHERE key=?',(request_key,)).fetchone()
        if not row:raise HTTPException(404,'未找到已提交任务。')
        return store.jobs.get(row[0])

    @router.post('/jobs/{job_id}/cancel')
    async def cancel_job(job_id: str):
        return await store.jobs.cancel(job_id)

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
