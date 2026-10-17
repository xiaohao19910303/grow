"""AI 行为分析报告 — API 路由。"""
from __future__ import annotations

from tenancy import scoped, learning_root, runtime_root
from datetime import date

from fastapi import APIRouter, FastAPI, HTTPException

from .store import BehaviorReportStore
from .analyzer import generate_report_content


def register(app: FastAPI, root, db_path) -> BehaviorReportStore:
    store = scoped(app, lambda: BehaviorReportStore(runtime_root(db_path)), initialize=True)
    router = APIRouter(prefix="/api/behavior-report")

    @router.post("/generate", status_code=201)
    async def generate_report(period_days: int = 30):
        if period_days < 7 or period_days > 365:
            raise HTTPException(400, "period_days must be 7-365")

        try:
            content, data_summary = await generate_report_content(db_path, period_days)
            report = store.create_report(
                dt=date.today().isoformat(),
                period_days=period_days,
                content=content,
                data_summary=data_summary,
            )
            return report
        except Exception as e:
            raise HTTPException(500, f"生成报告失败：{e}")

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
