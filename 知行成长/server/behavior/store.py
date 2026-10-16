"""行为应用追踪 — 数据层。

behavior_applications 表的 CRUD 和统计查询。
不修改任何现有表。
"""
from __future__ import annotations

import db
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


VALID_MODULES = {
    "fupan", "zhenghe", "renzhi", "xiezuo",
    "biaoda", "yingyu", "siwei", "gaorenzhi",
}

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS behavior_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module_id TEXT NOT NULL,
    concept TEXT NOT NULL,
    scenario TEXT DEFAULT '',
    effectiveness INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_behavior_date ON behavior_applications(date);
CREATE INDEX IF NOT EXISTS idx_behavior_module ON behavior_applications(module_id);
"""


class BehaviorStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.startup_error: Optional[Exception] = None

    def _conn(self) -> db.CompatConnection:
        conn = db.connect()
        return conn

    def initialize(self):
        """启动时建表。"""
        conn = self._conn()
        conn.executescript(TABLE_SQL)
        conn.commit()
        conn.close()

    # ── CRUD ──

    def create(
        self,
        dt: str,
        module_id: str,
        concept: str,
        scenario: str = "",
        effectiveness: int = 0,
    ) -> dict:
        if module_id not in VALID_MODULES:
            raise ValueError(f"invalid module_id: {module_id}")
        if not concept or not concept.strip():
            raise ValueError("concept is required")
        if len(concept) > 100:
            raise ValueError("concept must be ≤100 chars")
        if len(scenario) > 500:
            raise ValueError("scenario must be ≤500 chars")
        if not (0 <= effectiveness <= 5):
            raise ValueError("effectiveness must be 0-5")

        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO behavior_applications(date, module_id, concept, scenario, effectiveness) "
            "VALUES(?, ?, ?, ?, ?)",
            (dt, module_id, concept.strip(), scenario.strip(), effectiveness),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM behavior_applications WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        conn.close()
        return dict(row)

    def list(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        module_id: Optional[str] = None,
    ) -> list[dict]:
        clauses = []
        params = []
        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)
        if module_id:
            clauses.append("module_id = ?")
            params.append(module_id)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = self._conn()
        rows = conn.execute(
            f"SELECT * FROM behavior_applications{where} ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get(self, app_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM behavior_applications WHERE id = ?", (app_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update(self, app_id: int, **fields) -> Optional[dict]:
        existing = self.get(app_id)
        if not existing:
            return None

        allowed = {"date", "module_id", "concept", "scenario", "effectiveness"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

        if "module_id" in updates and updates["module_id"] not in VALID_MODULES:
            raise ValueError(f"invalid module_id: {updates['module_id']}")
        if "concept" in updates:
            if not updates["concept"].strip():
                raise ValueError("concept is required")
            if len(updates["concept"]) > 100:
                raise ValueError("concept must be ≤100 chars")
        if "scenario" in updates and len(updates["scenario"]) > 500:
            raise ValueError("scenario must be ≤500 chars")
        if "effectiveness" in updates and not (0 <= updates["effectiveness"] <= 5):
            raise ValueError("effectiveness must be 0-5")

        if not updates:
            return existing

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [app_id]
        conn = self._conn()
        conn.execute(
            f"UPDATE behavior_applications SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM behavior_applications WHERE id = ?", (app_id,)
        ).fetchone()
        conn.close()
        return dict(row)

    def delete(self, app_id: int) -> bool:
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM behavior_applications WHERE id = ?", (app_id,)
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    # ── Stats ──

    def get_stats(self, period_days: int = 30) -> dict:
        today = date.today()
        start = today - timedelta(days=period_days - 1)
        start_str = start.isoformat()
        end_str = today.isoformat()

        conn = self._conn()

        # total
        total = conn.execute(
            "SELECT COUNT(*) FROM behavior_applications WHERE date >= ? AND date <= ?",
            (start_str, end_str),
        ).fetchone()[0]

        # by_module
        by_module = {}
        for r in conn.execute(
            "SELECT module_id, COUNT(*) as cnt FROM behavior_applications "
            "WHERE date >= ? AND date <= ? GROUP BY module_id",
            (start_str, end_str),
        ):
            by_module[r["module_id"]] = r["cnt"]

        # top_concepts
        top_concepts = []
        for r in conn.execute(
            "SELECT concept, COUNT(*) as cnt FROM behavior_applications "
            "WHERE date >= ? AND date <= ? "
            "GROUP BY concept ORDER BY cnt DESC LIMIT 5",
            (start_str, end_str),
        ):
            top_concepts.append({"concept": r["concept"], "count": r["cnt"]})

        # trend (daily)
        daily_counts = {}
        for r in conn.execute(
            "SELECT date, COUNT(*) as cnt FROM behavior_applications "
            "WHERE date >= ? AND date <= ? GROUP BY date",
            (start_str, end_str),
        ):
            daily_counts[r["date"]] = r["cnt"]

        trend = []
        for i in range(period_days):
            d = (start + timedelta(days=i)).isoformat()
            trend.append({"date": d, "count": daily_counts.get(d, 0)})

        conn.close()
        return {
            "total": total,
            "period_days": period_days,
            "start": start_str,
            "end": end_str,
            "by_module": by_module,
            "top_concepts": top_concepts,
            "trend": trend,
        }

    def get_distinct_concepts(self) -> list[str]:
        """用于前端自动补全。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT concept FROM behavior_applications "
            "ORDER BY concept"
        ).fetchall()
        conn.close()
        return [r["concept"] for r in rows]
