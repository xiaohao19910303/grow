"""知识图谱可视化 — API 路由。"""
from __future__ import annotations

from tenancy import scoped, learning_root, runtime_root
import time
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException

from .store import KnowledgeGraphStore
from .graph import scan_links


def register(app: FastAPI, root, db_path) -> KnowledgeGraphStore:
    store = scoped(app, lambda: KnowledgeGraphStore(runtime_root(db_path)), initialize=True)
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
    def upsert_knowledge(data: dict):
        """幂等导入知识节点

        请求体应包含：name, category, summary, source, kind, date, source_path, source_hash
        如果 source_path + source_hash 已存在，则更新；否则插入新记录。
        """
        required_fields = ['name', 'category', 'summary', 'source', 'kind', 'date',
                          'source_path', 'source_hash']
        for field in required_fields:
            if field not in data:
                raise HTTPException(400, f"缺少必需字段: {field}")

        try:
            result = store.upsert_knowledge(**data)
            return {"ok": True, "knowledge": result}
        except Exception as e:
            raise HTTPException(500, f"导入失败: {e}")

    app.include_router(router)
    return store
