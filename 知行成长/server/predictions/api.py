"""预测校准可视化 — API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException

from .store import PredictionStats


def register(app: FastAPI, root, db_path) -> PredictionStats:
    stats = PredictionStats(db_path)
    router = APIRouter(prefix="/api/predictions")

    @router.get("/calibration")
    def get_calibration():
        return stats.get_calibration()

    @router.get("/stats")
    def get_accuracy_stats():
        return stats.get_accuracy_stats()

    @router.get("/overconfident")
    def get_overconfident(threshold: int = 80):
        if threshold < 50 or threshold > 100:
            raise HTTPException(400, "threshold must be 50-100")
        return stats.get_overconfident(threshold)

    @router.get("/trend")
    def get_trend(window: int = 10):
        if window < 3 or window > 50:
            raise HTTPException(400, "window must be 3-50")
        return stats.get_trend(window)

    app.include_router(router)
    return stats
