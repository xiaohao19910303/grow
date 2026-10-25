"""知识图谱可视化 — API 路由。"""
from __future__ import annotations

from tenancy import scoped, learning_root, runtime_root
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
import db

from .store import KnowledgeGraphStore
from .graph import scan_links


RequiredText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: RequiredText
    category: str = Field(strict=True, max_length=500)
    summary: str = Field(strict=True, max_length=100000)
    source: str = Field(strict=True, max_length=2000)
    kind: RequiredText
    date: str = Field(strict=True, max_length=100)
    source_path: RequiredText
    source_hash: RequiredText


def register(app: FastAPI, root, db_path) -> KnowledgeGraphStore:
    store = scoped(app, lambda: KnowledgeGraphStore(runtime_root(db_path)), initialize=True)

    def ready(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        if store.startup_error:
            raise HTTPException(503, '知识图谱存储暂不可用，请核对表结构和迁移状态。')

    router = APIRouter(prefix="/api/knowledge", dependencies=[Depends(ready)])

    @router.get("/graph")
    def get_graph(category: Optional[str] = None, limit: int = 500):
        if limit < 1 or limit > 1000:
            raise HTTPException(400, "limit must be 1-1000")
        return store.get_graph(category, limit)

    @router.post("/scan-links")
    def scan_knowledge_links():
        start = time.time()
        try:
            count = scan_links(db_path)
            elapsed = round((time.time() - start) * 1000)
            return {"ok": True, "links_created": count, "time_ms": elapsed}
        except Exception as e:
            raise HTTPException(500, f"扫描失败：{e}")

    @router.get("/stats")
    def get_stats():
        return store.get_stats()

    @router.get("/by-stable-id/{stable_id}")
    def get_by_stable_id(stable_id: str):
        """根据 stable_id 获取知识节点"""
        node = store.get_by_stable_id(stable_id)
        if not node:
            raise HTTPException(404, "知识节点不存在")
        return node

    @router.get("/by-stable-id/{stable_id}/related")
    def get_related_by_stable_id(stable_id: str, limit: int = 5):
        """获取与指定知识节点相关的其他节点"""
        if limit < 1 or limit > 20:
            raise HTTPException(400, "limit must be 1-20")
        node = store.get_by_stable_id(stable_id)
        if not node:
            raise HTTPException(404, "知识节点不存在")
        related = store.get_related_by_stable_id(stable_id, limit)
        return {"node": node, "related": related, "count": len(related)}

    @router.post("/upsert")
    def upsert_knowledge(data: KnowledgeInput):
        """幂等导入知识节点

        请求体应包含：name, category, summary, source, kind, date, source_path, source_hash
        source_path + name + kind 标识节点；source_hash 仅表示内容版本，更新时保留 ID。
        """
        try:
            result = store.upsert_knowledge(**data.model_dump())
            return {"ok": True, "knowledge": result}
        except db.psycopg2.Error:
            raise HTTPException(503, '知识节点保存失败，请稍后重试。') from None

    app.include_router(router)
    return store
