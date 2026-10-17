"""行为应用追踪 — API 路由。"""
from __future__ import annotations

from tenancy import scoped, learning_root, runtime_root
import re
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .store import BehaviorStore, VALID_MODULES


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApplicationCreate(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    module_id: str = Field(min_length=1, max_length=20)
    concept: str = Field(min_length=1, max_length=100)
    scenario: str = Field(default="", max_length=500)
    effectiveness: int = Field(default=0, ge=0, le=5)


class ApplicationUpdate(BaseModel):
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    module_id: Optional[str] = Field(default=None, min_length=1, max_length=20)
    concept: Optional[str] = Field(default=None, min_length=1, max_length=100)
    scenario: Optional[str] = Field(default=None, max_length=500)
    effectiveness: Optional[int] = Field(default=None, ge=0, le=5)


def register(app: FastAPI, root, db_path) -> BehaviorStore:
    store = scoped(app, lambda: BehaviorStore(runtime_root(db_path)), initialize=True)
    router = APIRouter(prefix="/api/behavior")

    def _validate_date(d: str):
        if not _DATE_RE.match(d):
            raise HTTPException(400, "date must be YYYY-MM-DD")
        return d

    @router.get("/applications")
    def list_applications(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        module_id: Optional[str] = None,
    ):
        if date_from:
            _validate_date(date_from)
        if date_to:
            _validate_date(date_to)
        if module_id and module_id not in VALID_MODULES:
            raise HTTPException(400, f"invalid module_id: {module_id}")
        return store.list(date_from, date_to, module_id)

    @router.post("/applications", status_code=201)
    def create_application(body: ApplicationCreate):
        _validate_date(body.date)
        try:
            return store.create(
                body.date, body.module_id, body.concept,
                body.scenario, body.effectiveness,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.get("/applications/concepts")
    def list_concepts():
        return store.get_distinct_concepts()

    @router.get("/applications/{app_id}")
    def get_application(app_id: int):
        row = store.get(app_id)
        if not row:
            raise HTTPException(404, "application not found")
        return row

    @router.put("/applications/{app_id}")
    def update_application(app_id: int, body: ApplicationUpdate):
        if body.date:
            _validate_date(body.date)
        try:
            row = store.update(app_id, **body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not row:
            raise HTTPException(404, "application not found")
        return row

    @router.delete("/applications/{app_id}", status_code=204)
    def delete_application(app_id: int):
        if not store.delete(app_id):
            raise HTTPException(404, "application not found")

    @router.get("/stats")
    def get_stats(period: int = 30):
        if period < 1 or period > 365:
            raise HTTPException(400, "period must be 1-365")
        return store.get_stats(period)

    app.include_router(router)
    return store
