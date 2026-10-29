"""AI 行为分析报告 — 数据层。"""
from __future__ import annotations

import db
from datetime import date
from pathlib import Path
from typing import Optional
from contextlib import contextmanager, closing


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
        from .jobs import ReportJobs
        self.jobs = ReportJobs(self)

    @contextmanager
    def conn(self):
        with closing(self._conn()) as c, c: yield c

    async def shutdown(self):
        await self.jobs.shutdown()

    def _conn(self) -> db.CompatConnection:
        conn = db.connect()
        return conn

    def initialize(self):
        """启动时建表。"""
        with self.conn() as conn:
            conn.executescript(TABLE_SQL)
            self.jobs.initialize(conn)

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
        from ai_evidence import metadata
        result=[{**dict(r),**metadata(conn,'behavior-result',r['id'])} for r in rows]
        conn.close()
        return result

    def get_report(self, report_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM behavior_reports WHERE id = ?", (report_id,)
        ).fetchone()
        from ai_evidence import metadata
        result={**dict(row),**metadata(conn,'behavior-result',row['id'])} if row else None
        conn.close()
        return result

    def delete_report(self, report_id: int) -> bool:
        from ai_evidence import release
        with self.conn() as conn:
            cur = conn.execute('DELETE FROM behavior_reports WHERE id=?', (report_id,))
            removed = cur.rowcount > 0
            if removed:
                for row in conn.execute('SELECT id,data FROM behavior_report_jobs WHERE result_id=?', (report_id,)).fetchall():
                    import json
                    job = json.loads(row['data']); job.update(result_id=None, result_deleted=True, evidence_snapshot_id=None, evidence_status='deleted', raw='', data_summary={}, phase='报告已删除')
                    conn.execute('UPDATE behavior_report_jobs SET result_id=NULL,data=? WHERE id=?',
                                 (json.dumps(job, ensure_ascii=False), row['id']))
                    release(conn, 'behavior-report', row['id'])
                release(conn, 'behavior-result', report_id)
            return removed
