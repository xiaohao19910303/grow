"""知识图谱可视化 — API 路由。"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException

from .store import KnowledgeGraphStore
from .graph import scan_links


def register(app: FastAPI, root, db_path) -> KnowledgeGraphStore:
    store = KnowledgeGraphStore(db_path)
    router = APIRouter(prefix="/api/knowledge")

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

    app.include_router(router)
    return store
