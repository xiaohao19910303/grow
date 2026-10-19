"""知识图谱可视化 — 关系检测。"""
from __future__ import annotations

import re
import db
from pathlib import Path
from collections import defaultdict


def extract_keywords(text: str) -> set[str]:
    """从文本中提取关键词（简单实现：提取中文词组和英文单词）。"""
    if not text:
        return set()

    # 提取中文（2-4字词组）
    chinese_words = re.findall(r'[一-龥]{2,4}', text)

    # 提取英文单词
    english_words = re.findall(r'[a-zA-Z]{3,}', text.lower())

    # 合并并去重
    keywords = set(chinese_words + english_words)

    # 过滤常见词
    stop_words = {'的', '是', '在', '和', '与', '或', '有', '也', '都', '就', '不', '了', '这', '那', 'the', 'and', 'for', 'with'}
    return keywords - stop_words


def detect_links(db_path: Path) -> list[tuple]:
    """检测知识节点之间的关系。返回 (source_id, target_id, link_type, weight) 列表。"""
    conn = db.connect()
    nodes = conn.execute("SELECT * FROM knowledge").fetchall()
    if not nodes:
        conn.close()
        return []

    links = []

    # 1. 同源关系：来自同一个 source 的节点
    nodes_by_source = defaultdict(list)
    for n in nodes:
        if n["source"]:
            nodes_by_source[n["source"]].append(n["id"])

    for source, node_ids in nodes_by_source.items():
        if len(node_ids) > 1:
            for i, id1 in enumerate(node_ids):
                for id2 in node_ids[i+1:]:
                    links.append((id1, id2, 'same_source', 3))

    # 2. 关键词共现：summary 中包含相同关键词
    node_keywords = {}
    for n in nodes:
        keywords = extract_keywords(n["summary"] or "")
        if keywords:
            node_keywords[n["id"]] = keywords

    # 检测关键词共现（只检测前100个节点，避免 O(n^2) 太慢）
    node_list = list(node_keywords.items())[:100]
    for i, (id1, kw1) in enumerate(node_list):
        for id2, kw2 in node_list[i+1:]:
            common = kw1 & kw2
            if len(common) >= 2:  # 至少2个共同关键词
                weight = min(len(common), 5)
                links.append((id1, id2, 'keyword', weight))

    # 3. 分类关系：同一 category 的节点（弱关联）
    nodes_by_category = defaultdict(list)
    for n in nodes:
        if n["category"]:
            nodes_by_category[n["category"]].append(n["id"])

    for category, node_ids in nodes_by_category.items():
        if len(node_ids) > 1:
            # 每个分类最多连接20对，避免边太多
            count = 0
            for i, id1 in enumerate(node_ids):
                if count >= 20:
                    break
                for id2 in node_ids[i+1:]:
                    if count >= 20:
                        break
                    links.append((id1, id2, 'category', 1))
                    count += 1

    conn.close()
    return links


def scan_links(db_path: Path) -> int:
    """扫描并保存关系。返回保存的数量。"""
    from .store import KnowledgeGraphStore

    store = KnowledgeGraphStore(db_path)
    store.clear_links()
    links = detect_links(db_path)
    return store.save_links(links)
