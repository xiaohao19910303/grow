"""错误追踪 — API 路由。"""
from __future__ import annotations

from tenancy import scoped, learning_root, runtime_root
import re
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .store import ErrorStore, VALID_MODULES


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErrorCreate(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    module_id: str = Field(min_length=1, max_length=20)
    error_type: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    severity: int = Field(default=3, ge=0, le=5)
    context: str = Field(default="", max_length=500)
    improvement_action: str = Field(default="", max_length=500)
    is_repeat: int = Field(default=0, ge=0, le=1)
    related_error_id: Optional[int] = Field(default=None)


class ErrorUpdate(BaseModel):
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    module_id: Optional[str] = Field(default=None, min_length=1, max_length=20)
    error_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    severity: Optional[int] = Field(default=None, ge=0, le=5)
    context: Optional[str] = Field(default=None, max_length=500)
    improvement_action: Optional[str] = Field(default=None, max_length=500)
    is_repeat: Optional[int] = Field(default=None, ge=0, le=1)
    related_error_id: Optional[int] = Field(default=None)


class ErrorTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)


def register(app: FastAPI, root, db_path) -> ErrorStore:
    store = scoped(app, lambda: ErrorStore(runtime_root(db_path)), initialize=True)
    router = APIRouter(prefix="/api/errors")

    def _validate_date(d: str):
        if not _DATE_RE.match(d):
            raise HTTPException(400, "date must be YYYY-MM-DD")
        return d

    @router.get("/")
    def list_errors(
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        module_id: Optional[str] = None,
        error_type: Optional[str] = None,
        is_repeat: Optional[int] = None,
    ):
        if date_from:
            _validate_date(date_from)
        if date_to:
            _validate_date(date_to)
        if module_id and module_id not in VALID_MODULES:
            raise HTTPException(400, f"invalid module_id: {module_id}")
        return store.list_errors(date_from, date_to, module_id, error_type, is_repeat)

    @router.post("/", status_code=201)
    def create_error(body: ErrorCreate):
        _validate_date(body.date)
        try:
            return store.create_error(
                body.date, body.module_id, body.error_type,
                body.description, body.severity, body.context,
                body.improvement_action, body.is_repeat, body.related_error_id,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.get("/types")
    def list_error_types():
        return store.list_error_types()

    @router.post("/types", status_code=201)
    def create_error_type(body: ErrorTypeCreate):
        try:
            return store.create_error_type(body.name, body.description)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.delete("/types/{type_id}", status_code=204)
    def delete_error_type(type_id: int):
        try:
            if not store.delete_error_type(type_id):
                raise HTTPException(404, "error_type not found")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.get("/stats")
    def get_stats(period: int = 30):
        if period < 1 or period > 365:
            raise HTTPException(400, "period must be 1-365")
        return store.get_stats(period)

    @router.get("/repeated")
    def get_repeated_errors():
        return store.get_repeated_errors()

    @router.get("/{error_id}")
    def get_error(error_id: int):
        row = store.get_error(error_id)
        if not row:
            raise HTTPException(404, "error not found")
        return row

    @router.put("/{error_id}")
    def update_error(error_id: int, body: ErrorUpdate):
        if body.date:
            _validate_date(body.date)
        try:
            row = store.update_error(error_id, **body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not row:
            raise HTTPException(404, "error not found")
        return row

    @router.delete("/{error_id}", status_code=204)
    def delete_error(error_id: int):
        if not store.delete_error(error_id):
            raise HTTPException(404, "error not found")

    app.include_router(router)
    return store
