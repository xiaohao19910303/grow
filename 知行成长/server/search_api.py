"""统一搜索 API 路由

提供跨模块搜索的 REST API 端点。
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query

from search_service import SearchService


def register(app: FastAPI, db_path: Path) -> SearchService:
    """注册搜索 API 路由"""
    search_service = SearchService(db_path)
    router = APIRouter(prefix="/api/search")

    @router.get("")
    def search(
        q: str = Query(..., description="搜索关键词"),
        types: Optional[str] = Query(None, description="模块类型，逗号分隔"),
        start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
        end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    ):
        """执行跨模块搜索

        搜索范围包括：学习记录、反思日志、决策记录、预测记录、知识图谱
        """
        if not q or not q.strip():
            raise HTTPException(status_code=400, detail="搜索关键词不能为空")

        # 解析模块类型
        module_types = None
        if types:
            module_types = [t.strip() for t in types.split(',') if t.strip()]

        try:
            result = search_service.search(
                query=q,
                module_types=module_types,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=page_size,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"搜索失败: {e}")

    @router.get("/stats")
    def get_stats():
        """获取各模块的搜索统计信息"""
        try:
            return search_service.get_search_stats()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取统计失败: {e}")

    app.include_router(router)
    return search_service
