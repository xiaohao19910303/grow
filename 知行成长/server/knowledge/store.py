"""知识图谱可视化 — 数据层。"""
from __future__ import annotations

import db
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from .schema import upgrade_stable_ids


TABLE_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    link_type TEXT DEFAULT 'related',
    weight INTEGER DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES knowledge(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES knowledge(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_link_source ON knowledge_links(source_id);
CREATE INDEX IF NOT EXISTS idx_link_target ON knowledge_links(target_id);
"""


class KnowledgeGraphStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.startup_error: Optional[Exception] = None

    def _conn(self) -> db.CompatConnection:
        conn = db.connect()
        return conn

    def initialize(self):
        """启动时建表。"""
        with self._conn() as conn:
            conn.executescript(TABLE_SQL)
            upgrade_stable_ids(conn)

    def get_by_stable_id(self, stable_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute('SELECT * FROM knowledge WHERE stable_id=?', (stable_id,)).fetchone()
            return dict(row) if row else None

    def get_related_by_stable_id(self, stable_id: str, limit: int = 5) -> list[dict]:
        with self._conn() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT k.*, MAX(l.weight) AS weight FROM knowledge k
                JOIN knowledge_links l ON l.source_id=k.id OR l.target_id=k.id
                JOIN knowledge origin ON origin.stable_id=?
                WHERE k.id<>origin.id AND
                  ((l.source_id=origin.id AND l.target_id=k.id) OR
                   (l.target_id=origin.id AND l.source_id=k.id))
                GROUP BY k.id ORDER BY weight DESC,k.id LIMIT ?
            """, (stable_id, limit))]

    def upsert_knowledge(self, *, name, category, summary, source, kind, date, source_path, source_hash):
        """Identity is path/name/kind; a changed content hash updates the same node."""
        with self._conn() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':knowledge-write',0))")
            matches = conn.execute('SELECT * FROM knowledge WHERE source_path=? AND name=? AND kind=? ORDER BY id FOR UPDATE',
                                   (source_path, name, kind)).fetchall()
            if not matches:
                matches = conn.execute("""SELECT * FROM knowledge WHERE
                    (source_path IS NULL OR source_path='') AND name=? AND COALESCE(source,'')=?
                    AND COALESCE(kind,'')=? ORDER BY id FOR UPDATE""", (name, source, kind)).fetchall()
            if len(matches) > 1:
                raise HTTPException(409, '存在多个同源知识节点，请核对原记录后再导入；原节点和关系均已保留。')
            values = (name, category, summary, source, kind, date, source_path, source_hash)
            if matches:
                row = conn.execute("""UPDATE knowledge SET name=?,category=?,summary=?,source=?,kind=?,date=?,
                    source_path=?,source_hash=? WHERE id=? RETURNING *""", (*values, matches[0]['id'])).fetchone()
            else:
                row = conn.execute("""INSERT INTO knowledge(name,category,summary,source,kind,date,source_path,source_hash)
                    VALUES (?,?,?,?,?,?,?,?) RETURNING *""", values).fetchone()
            return dict(row)

    def get_graph(self, category: Optional[str] = None, limit: int = 500) -> dict:
        """获取图谱数据（nodes + links）。"""
        conn = self._conn()

        # 获取节点
        if category:
            nodes_sql = "SELECT * FROM knowledge WHERE category = ? ORDER BY id LIMIT ?"
            nodes_rows = conn.execute(nodes_sql, (category, limit)).fetchall()
        else:
            nodes_sql = "SELECT * FROM knowledge ORDER BY id LIMIT ?"
            nodes_rows = conn.execute(nodes_sql, (limit,)).fetchall()

        nodes = [dict(r) for r in nodes_rows]
        node_ids = {n["id"] for n in nodes}

        # 计算每个节点的连接数（用于调整大小）
        link_counts = {}
        for nid in node_ids:
            count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_links "
                "WHERE source_id = ? OR target_id = ?",
                (nid, nid),
            ).fetchone()[0]
            link_counts[nid] = count

        # 为节点添加 size 字段
        for n in nodes:
            base_size = 8
            n["size"] = base_size + min(link_counts.get(n["id"], 0) * 2, 20)

        # 获取关系（只包含在 nodes 中的）
        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            links_sql = f"""
                SELECT source_id, target_id, link_type, weight
                FROM knowledge_links
                WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                ORDER BY weight DESC
                LIMIT 1000
            """
            links_rows = conn.execute(links_sql, list(node_ids) * 2).fetchall()
            links = [dict(r) for r in links_rows]
        else:
            links = []

        # 统计
        total_nodes = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        total_links = conn.execute("SELECT COUNT(*) FROM knowledge_links").fetchone()[0]

        categories = {}
        for r in conn.execute(
            "SELECT category, COUNT(*) as cnt FROM knowledge GROUP BY category"
        ):
            categories[r["category"] or "未分类"] = r["cnt"]

        conn.close()

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_nodes": total_nodes,
                "total_links": total_links,
                "categories": categories,
            },
        }

    def save_links(self, links: list[tuple]) -> int:
        """保存关系列表。返回保存的数量。"""
        if not links:
            return 0

        conn = self._conn()
        count = 0
        for source_id, target_id, link_type, weight in links:
            try:
                conn.execute(
                    "INSERT INTO knowledge_links(source_id, target_id, link_type, weight) "
                    "VALUES(?, ?, ?, ?) ON CONFLICT(source_id,target_id,link_type) DO NOTHING",
                    (source_id, target_id, link_type, weight),
                )
                count += 1
            except db.IntegrityError:
                pass
        conn.commit()
        conn.close()
        return count

    def clear_links(self):
        """清空所有关系。"""
        conn = self._conn()
        conn.execute("DELETE FROM knowledge_links")
        conn.commit()
        conn.close()

    def get_stats(self) -> dict:
        """获取统计信息。"""
        conn = self._conn()
        total_nodes = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        total_links = conn.execute("SELECT COUNT(*) FROM knowledge_links").fetchone()[0]

        categories = {}
        for r in conn.execute(
            "SELECT category, COUNT(*) as cnt FROM knowledge GROUP BY category"
        ):
            categories[r["category"] or "未分类"] = r["cnt"]

        conn.close()
        return {
            "total_nodes": total_nodes,
            "total_links": total_links,
            "categories": categories,
        }
