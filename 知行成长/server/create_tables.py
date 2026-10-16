#!/usr/bin/env python3
"""在 Supabase 中创建所有模块的表"""

import db
import sys
import os

# 添加 server 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def create_tables():
    """创建所有模块的表"""
    conn = db.connect()
    cursor = conn.cursor()

    # 1. Copilot 模块表
    print("创建 copilot 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_settings (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_meta (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_lessons (
            lesson_no INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_learning_records (
            lesson_no INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_drafts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_generation_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copilot_operations (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 2. Plans 模块表
    print("创建 plans 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_plans (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_plan_versions (
            plan_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, version)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_lessons (
            plan_id TEXT NOT NULL,
            lesson_no INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, lesson_no)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_drafts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_ai_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_feedback (
            plan_id TEXT NOT NULL,
            lesson_no INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, lesson_no)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_publications (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_draft_families (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_settings (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 3. Reading 模块表
    print("创建 reading 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_vocabulary (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_reviews (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 4. Reflections 模块表
    print("创建 reflections 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reflection_entries (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reflection_versions (
            entry_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (entry_id, version)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reflection_ai_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reflection_operations (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 5. Stocks 模块表
    print("创建 stocks 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 6. Errors 模块表
    print("创建 errors 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_types (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 7. Predictions 模块表
    print("创建 predictions 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prediction_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 8. Behavior 模块表
    print("创建 behavior 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS behavior_applications (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 9. Behavior Report 模块表
    print("创建 behavior_report 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS behavior_reports (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    # 10. Knowledge 模块表
    print("创建 knowledge 模块表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_links (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("\n✅ 所有模块表创建完成！")

if __name__ == '__main__':
    create_tables()
