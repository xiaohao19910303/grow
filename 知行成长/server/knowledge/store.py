"""知识图谱可视化 — 数据层。"""
from __future__ import annotations

import db
from pathlib import Path
from typing import Optional


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
        conn = self._conn()
        conn.executescript(TABLE_SQL)
        conn.commit()
        conn.close()

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
                    "INSERT OR IGNORE INTO knowledge_links(source_id, target_id, link_type, weight) "
                    "VALUES(?, ?, ?, ?)",
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
