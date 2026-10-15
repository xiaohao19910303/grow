"""错误追踪 — 数据层。

error_records 表和 error_types 表的 CRUD 和统计查询。
不修改任何现有表。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


VALID_MODULES = {
    "fupan", "zhenghe", "renzhi", "xiezuo",
    "biaoda", "yingyu", "siwei", "gaorenzhi",
}

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS error_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module_id TEXT NOT NULL,
    error_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity INTEGER DEFAULT 3,
    context TEXT DEFAULT '',
    improvement_action TEXT DEFAULT '',
    is_repeat INTEGER DEFAULT 0,
    related_error_id INTEGER DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (related_error_id) REFERENCES error_records(id)
);
CREATE INDEX IF NOT EXISTS idx_error_date ON error_records(date);
CREATE INDEX IF NOT EXISTS idx_error_module ON error_records(module_id);
CREATE INDEX IF NOT EXISTS idx_error_type ON error_records(error_type);
CREATE INDEX IF NOT EXISTS idx_error_repeat ON error_records(is_repeat);

CREATE TABLE IF NOT EXISTS error_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

DEFAULT_ERROR_TYPES = [
    ("判断偏差", "高估或低估某事物的难度/重要性"),
    ("步骤遗漏", "执行过程中遗漏关键步骤"),
    ("概念混淆", "对某个概念的理解有偏差"),
    ("注意力分散", "执行时注意力不集中导致错误"),
    ("时间估算错误", "低估或高估所需时间"),
    ("沟通误解", "与他人沟通时产生误解"),
    ("过度自信", "认为自己掌握了但实际没有"),
    ("其他", "不属于以上类别的错误"),
]


class ErrorStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.startup_error: Optional[Exception] = None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        """启动时建表并预置错误类型。"""
        conn = self._conn()
        conn.executescript(TABLE_SQL)
        # 预置错误类型
        for name, desc in DEFAULT_ERROR_TYPES:
            try:
                conn.execute(
                    "INSERT INTO error_types(name, description) VALUES(?, ?)",
                    (name, desc),
                )
            except sqlite3.IntegrityError:
                pass  # 已存在
        conn.commit()
        conn.close()

    # ── Error Records CRUD ──

    def create_error(
        self,
        dt: str,
        module_id: str,
        error_type: str,
        description: str,
        severity: int = 3,
        context: str = "",
        improvement_action: str = "",
        is_repeat: int = 0,
        related_error_id: Optional[int] = None,
    ) -> dict:
        if module_id not in VALID_MODULES:
            raise ValueError(f"invalid module_id: {module_id}")
        if not error_type or not error_type.strip():
            raise ValueError("error_type is required")
        if len(error_type) > 50:
            raise ValueError("error_type must be ≤50 chars")
        if not description or not description.strip():
            raise ValueError("description is required")
        if len(description) > 500:
            raise ValueError("description must be ≤500 chars")
        if not (0 <= severity <= 5):
            raise ValueError("severity must be 0-5")
        if len(context) > 500:
            raise ValueError("context must be ≤500 chars")
        if len(improvement_action) > 500:
            raise ValueError("improvement_action must be ≤500 chars")

        conn = self._conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO error_records(date, module_id, error_type, description, "
            "severity, context, improvement_action, is_repeat, related_error_id) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dt, module_id, error_type.strip(), description.strip(), severity,
             context.strip(), improvement_action.strip(), is_repeat, related_error_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM error_records WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        conn.close()
        return dict(row)

    def list_errors(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        module_id: Optional[str] = None,
        error_type: Optional[str] = None,
        is_repeat: Optional[int] = None,
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
        if error_type:
            clauses.append("error_type = ?")
            params.append(error_type)
        if is_repeat is not None:
            clauses.append("is_repeat = ?")
            params.append(is_repeat)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = self._conn()
        rows = conn.execute(
            f"SELECT * FROM error_records{where} ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_error(self, error_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM error_records WHERE id = ?", (error_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_error(self, error_id: int, **fields) -> Optional[dict]:
        existing = self.get_error(error_id)
        if not existing:
            return None

        allowed = {"date", "module_id", "error_type", "description", "severity",
                   "context", "improvement_action", "is_repeat", "related_error_id"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

        if "module_id" in updates and updates["module_id"] not in VALID_MODULES:
            raise ValueError(f"invalid module_id: {updates['module_id']}")
        if "error_type" in updates:
            if not updates["error_type"].strip():
                raise ValueError("error_type is required")
            if len(updates["error_type"]) > 50:
                raise ValueError("error_type must be ≤50 chars")
        if "description" in updates:
            if not updates["description"].strip():
                raise ValueError("description is required")
            if len(updates["description"]) > 500:
                raise ValueError("description must be ≤500 chars")
        if "severity" in updates and not (0 <= updates["severity"] <= 5):
            raise ValueError("severity must be 0-5")
        if "context" in updates and len(updates["context"]) > 500:
            raise ValueError("context must be ≤500 chars")
        if "improvement_action" in updates and len(updates["improvement_action"]) > 500:
            raise ValueError("improvement_action must be ≤500 chars")

        if not updates:
            return existing

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [error_id]
        conn = self._conn()
        conn.execute(
            f"UPDATE error_records SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM error_records WHERE id = ?", (error_id,)
        ).fetchone()
        conn.close()
        return dict(row)

    def delete_error(self, error_id: int) -> bool:
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM error_records WHERE id = ?", (error_id,)
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    # ── Error Types ──

    def create_error_type(self, name: str, description: str = "") -> dict:
        if not name or not name.strip():
            raise ValueError("name is required")
        if len(name) > 50:
            raise ValueError("name must be ≤50 chars")
        if len(description) > 200:
            raise ValueError("description must be ≤200 chars")

        conn = self._conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO error_types(name, description) VALUES(?, ?)",
                (name.strip(), description.strip()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM error_types WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            conn.close()
            return dict(row)
        except sqlite3.IntegrityError:
            conn.close()
            raise ValueError(f"error_type '{name}' already exists")

    def list_error_types(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM error_types ORDER BY name"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_error_type(self, type_id: int) -> bool:
        conn = self._conn()
        # 检查是否被引用
        ref_count = conn.execute(
            "SELECT COUNT(*) FROM error_records WHERE error_type = "
            "(SELECT name FROM error_types WHERE id = ?)",
            (type_id,),
        ).fetchone()[0]
        if ref_count > 0:
            conn.close()
            raise ValueError(f"error_type is referenced by {ref_count} error records")

        cur = conn.execute(
            "DELETE FROM error_types WHERE id = ?", (type_id,)
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
            "SELECT COUNT(*) FROM error_records WHERE date >= ? AND date <= ?",
            (start_str, end_str),
        ).fetchone()[0]

        # by_type
        by_type = {}
        for r in conn.execute(
            "SELECT error_type, COUNT(*) as cnt FROM error_records "
            "WHERE date >= ? AND date <= ? GROUP BY error_type",
            (start_str, end_str),
        ):
            by_type[r["error_type"]] = r["cnt"]

        # by_module
        by_module = {}
        for r in conn.execute(
            "SELECT module_id, COUNT(*) as cnt FROM error_records "
            "WHERE date >= ? AND date <= ? GROUP BY module_id",
            (start_str, end_str),
        ):
            by_module[r["module_id"]] = r["cnt"]

        # severity_avg
        severity_avg = conn.execute(
            "SELECT AVG(severity) FROM error_records WHERE date >= ? AND date <= ?",
            (start_str, end_str),
        ).fetchone()[0]
        severity_avg = round(severity_avg, 1) if severity_avg else 0

        # repeat_rate
        repeat_count = conn.execute(
            "SELECT COUNT(*) FROM error_records WHERE date >= ? AND date <= ? AND is_repeat = 1",
            (start_str, end_str),
        ).fetchone()[0]
        repeat_rate = round(repeat_count / total, 2) if total > 0 else 0

        # trend (daily)
        daily_counts = {}
        for r in conn.execute(
            "SELECT date, COUNT(*) as cnt FROM error_records "
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
            "by_type": by_type,
            "by_module": by_module,
            "severity_avg": severity_avg,
            "repeat_rate": repeat_rate,
            "trend": trend,
        }

    def get_repeated_errors(self) -> list[dict]:
        """按错误类型分组，找出出现2次以上的错误组。"""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM error_records ORDER BY error_type, date"
        ).fetchall()
        conn.close()

        groups = {}
        for r in rows:
            row = dict(r)
            key = row["error_type"]
            if key not in groups:
                groups[key] = []
            groups[key].append(row)

        repeated = []
        for error_type, errors in groups.items():
            if len(errors) >= 2:
                repeated.append({
                    "error_type": error_type,
                    "count": len(errors),
                    "first_occurrence": min(e["date"] for e in errors),
                    "last_occurrence": max(e["date"] for e in errors),
                    "errors": sorted(errors, key=lambda e: e["date"]),
                })

        return sorted(repeated, key=lambda g: g["count"], reverse=True)

    def count_recent_same_type(self, error_type: str, days: int = 30) -> int:
        """检查近N天内是否有相同类型的错误。"""
        today = date.today()
        start = today - timedelta(days=days - 1)
        start_str = start.isoformat()
        end_str = today.isoformat()

        conn = self._conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM error_records "
            "WHERE error_type = ? AND date >= ? AND date <= ?",
            (error_type, start_str, end_str),
        ).fetchone()[0]
        conn.close()
        return count
