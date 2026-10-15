"""AI 行为分析报告 — 数据层。"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional


TABLE_SQL = """
CREATE TABLE IF NOT EXISTS behavior_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    period_days INTEGER NOT NULL,
    content TEXT NOT NULL,
    data_summary TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_report_date ON behavior_reports(date);
"""


class BehaviorReportStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.startup_error: Optional[Exception] = None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        """启动时建表。"""
        conn = self._conn()
        conn.executescript(TABLE_SQL)
        conn.commit()
        conn.close()

    def create_report(
        self,
        dt: str,
        period_days: int,
        content: str,
        data_summary: str = "",
    ) -> dict:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO behavior_reports(date, period_days, content, data_summary) "
            "VALUES(?, ?, ?, ?)",
            (dt, period_days, content, data_summary),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM behavior_reports WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        conn.close()
        return dict(row)

    def list_reports(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM behavior_reports ORDER BY date DESC, id DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_report(self, report_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM behavior_reports WHERE id = ?", (report_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_report(self, report_id: int) -> bool:
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM behavior_reports WHERE id = ?", (report_id,)
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0
