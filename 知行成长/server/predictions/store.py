"""预测校准可视化 — 数据层。

复用现有 predictions 表，提供校准统计分析。
"""
from __future__ import annotations

import db
from pathlib import Path
from typing import Optional


class PredictionStats:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> db.CompatConnection:
        conn = db.connect()
        return conn

    def get_calibration(self) -> dict:
        """分桶统计校准数据（10 个桶：0-10, 10-20, ..., 90-100）。"""
        conn = self._conn()

        # 总数统计
        total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE result = 'pending'"
        ).fetchone()[0]
        resolved = total - pending

        buckets = []
        for i in range(10):
            min_p = i * 10
            max_p = (i + 1) * 10

            # 该桶的总数（排除 pending）
            count = conn.execute(
                "SELECT COUNT(*) FROM predictions "
                "WHERE probability >= ? AND probability < ? AND result != 'pending'",
                (min_p, max_p),
            ).fetchone()[0]

            # 正确数
            correct = conn.execute(
                "SELECT COUNT(*) FROM predictions "
                "WHERE probability >= ? AND probability < ? AND result = 'correct'",
                (min_p, max_p),
            ).fetchone()[0]

            rate = round(correct / count, 2) if count > 0 else 0

            buckets.append({
                "range": f"{min_p}-{max_p}",
                "min": min_p,
                "max": max_p,
                "count": count,
                "correct": correct,
                "rate": rate,
            })

        # 特殊处理 100% 桶（包含 100）
        count_100 = conn.execute(
            "SELECT COUNT(*) FROM predictions "
            "WHERE probability = 100 AND result != 'pending'"
        ).fetchone()[0]
        correct_100 = conn.execute(
            "SELECT COUNT(*) FROM predictions "
            "WHERE probability = 100 AND result = 'correct'"
        ).fetchone()[0]

        if count_100 > 0:
            # 合并到 90-100 桶
            buckets[9]["count"] += count_100
            buckets[9]["correct"] += correct_100
            buckets[9]["rate"] = round(
                buckets[9]["correct"] / buckets[9]["count"], 2
            ) if buckets[9]["count"] > 0 else 0

        conn.close()
        return {
            "buckets": buckets,
            "total": total,
            "resolved": resolved,
            "pending": pending,
        }

    def get_accuracy_stats(self) -> dict:
        """计算 Brier Score, 准确率, 平均概率, 校准误差。"""
        conn = self._conn()

        total = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE result = 'pending'"
        ).fetchone()[0]
        resolved = total - pending

        correct = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE result = 'correct'"
        ).fetchone()[0]
        accuracy = round(correct / resolved, 2) if resolved > 0 else 0

        # Brier Score
        brier_score = 0
        if resolved > 0:
            rows = conn.execute(
                "SELECT probability, result FROM predictions WHERE result != 'pending'"
            ).fetchall()
            for r in rows:
                p = r["probability"] / 100
                outcome = 1 if r["result"] == "correct" else 0
                brier_score += (p - outcome) ** 2
            brier_score = round(brier_score / resolved, 3)

        # 平均概率
        avg_prob = conn.execute(
            "SELECT AVG(probability) FROM predictions WHERE result != 'pending'"
        ).fetchone()[0]
        avg_probability = round(avg_prob) if avg_prob else 0

        # 校准误差
        calibration_data = self.get_calibration()
        calibration_error = 0
        bucket_count = 0
        for bucket in calibration_data["buckets"]:
            if bucket["count"] > 0:
                bucket_median = (bucket["min"] + bucket["max"]) / 200
                calibration_error += abs(bucket["rate"] - bucket_median)
                bucket_count += 1
        calibration_error = (
            round(calibration_error / bucket_count, 3) if bucket_count > 0 else 0
        )

        conn.close()
        return {
            "total": total,
            "resolved": resolved,
            "correct": correct,
            "accuracy": accuracy,
            "pending": pending,
            "brier_score": brier_score,
            "avg_probability": avg_probability,
            "calibration_error": calibration_error,
        }

    def get_overconfident(self, threshold: int = 80) -> list[dict]:
        """获取过度自信事件（高概率但实际错误）。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM predictions "
            "WHERE probability >= ? AND result = 'incorrect' "
            "ORDER BY probability DESC, date DESC",
            (threshold,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_trend(self, window: int = 10) -> dict:
        """计算滚动准确率（滑动窗口）。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT date, result FROM predictions "
            "WHERE result != 'pending' "
            "ORDER BY date ASC, id ASC"
        ).fetchall()
        conn.close()

        if len(rows) < window:
            return {"trend": [], "total_windows": 0}

        trend = []
        for i in range(len(rows) - window + 1):
            window_rows = rows[i:i + window]
            correct = sum(1 for r in window_rows if r["result"] == "correct")
            accuracy = round(correct / window, 2)
            trend.append({
                "index": i + 1,
                "date": window_rows[-1]["date"],
                "accuracy": accuracy,
                "window_size": window,
            })

        return {"trend": trend, "total_windows": len(trend)}
