"""时间线 API 路由

提供跨模块时间线聚合的 REST API 端点。
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query

from timeline_service import TimelineService


def register(app: FastAPI, db_path: Path) -> TimelineService:
    """注册时间线 API 路由"""
    timeline_service = TimelineService(db_path)
    router = APIRouter(prefix="/api/timeline")

    @router.get("")
    def get_timeline(
        start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
        end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
        types: Optional[str] = Query(None, description="模块类型，逗号分隔"),
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    ):
        """获取时间线数据

        聚合多个模块的记录，按日期排序：
        学习记录、反思日志、决策记录、预测记录、复盘记录、灵感记录、知识图谱
        """
        # 解析模块类型
        module_types = None
        if types:
            module_types = [t.strip() for t in types.split(',') if t.strip()]

        try:
            result = timeline_service.get_timeline(
                start_date=start_date,
                end_date=end_date,
                module_types=module_types,
                page=page,
                page_size=page_size,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取时间线失败: {e}")

    @router.get("/stats")
    def get_stats(start_date: Optional[str] = None, end_date: Optional[str] = None, types: Optional[str] = None):
        """获取各模块的时间线统计信息"""
        try:
            return timeline_service.get_timeline_stats(start_date, end_date, [t.strip() for t in types.split(',') if t.strip()] if types else None)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取统计失败: {e}")

    app.include_router(router)
    return timeline_service
