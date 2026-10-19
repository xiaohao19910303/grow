#!/usr/bin/env python3
"""
数据迁移脚本：从本地 SQLite 迁移到 PostgreSQL (Supabase)

使用方法：
    python3 migrate_data.py

该脚本会：
1. 读取本地 data.db 中的所有数据
2. 将数据插入到 Supabase PostgreSQL 数据库中
3. 显示迁移统计
"""

import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
import os
import sys
from pathlib import Path

# 配置
SQLITE_DB = Path(__file__).parent / "data.db"
POSTGRES_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:SHUAIge.zhixingchengzhang@db.cafdvxlzmqavmvospgvd.supabase.co:5432/postgres'
)

def migrate_table(sqlite_conn, pg_conn, table_name, columns=None):
    """迁移单个表的数据"""
    try:
        # 从 SQLite 读取数据
        if columns:
            cursor = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table_name}")
        else:
            cursor = sqlite_conn.execute(f"SELECT * FROM {table_name}")

        rows = cursor.fetchall()
        if not rows:
            print(f"  {table_name}: 无数据")
            return 0

        # 获取列名
        if columns:
            col_names = columns
        else:
            col_names = [desc[0] for desc in cursor.description]

        # 构建 INSERT 语句
        placeholders = ', '.join(['%s'] * len(col_names))
        insert_sql = f"INSERT INTO {table_name} ({', '.join(col_names)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        # 插入到 PostgreSQL
        pg_cursor = pg_conn.cursor()
        inserted = 0
        for row in rows:
            try:
                pg_cursor.execute(insert_sql, row)
                inserted += 1
            except psycopg2.Error as e:
                print(f"    ⚠️  插入失败: {e}")
                pg_conn.rollback()
                continue

        pg_conn.commit()
        print(f"  {table_name}: ✅ {inserted}/{len(rows)} 行")
        return inserted

    except sqlite3.Error as e:
        print(f"  {table_name}: ❌ SQLite 错误 - {e}")
        return 0
    except psycopg2.Error as e:
        print(f"  {table_name}: ❌ PostgreSQL 错误 - {e}")
        pg_conn.rollback()
        return 0

def main():
    """主迁移函数"""
    print("=" * 60)
    print("知行成长 - 数据迁移工具")
    print("=" * 60)
    print()

    # 检查 SQLite 数据库是否存在
    if not SQLITE_DB.exists():
        print(f"❌ SQLite 数据库不存在: {SQLITE_DB}")
        print("   如果没有旧数据，可以跳过此步骤。")
        return

    print(f"SQLite 数据库: {SQLITE_DB}")
    print(f"PostgreSQL: {POSTGRES_URL[:50]}...")
    print()

    # 连接数据库
    try:
        sqlite_conn = sqlite3.connect(str(SQLITE_DB))
        pg_conn = psycopg2.connect(POSTGRES_URL)
        print("✅ 数据库连接成功")
        print()
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return

    # 定义要迁移的表
    tables = [
        # 核心表
        ('todos', None),
        ('modules', None),
        ('checkins', None),
        ('habits', None),
        ('custom_fields', None),
        ('custom_records', None),
        ('decisions', None),
        ('predictions', None),
        ('reviews', None),
        ('insights', None),
        ('knowledge', None),

        # Copilot 模块
        ('copilot_settings', None),
        ('copilot_meta', None),
        ('copilot_lessons', None),
        ('copilot_learning_records', None),
        ('copilot_drafts', None),
        ('copilot_generation_attempts', None),
        ('copilot_operations', None),

        # Plans 模块
        ('learning_plans', None),
        ('learning_plan_versions', None),
        ('learning_lessons', None),
        ('learning_drafts', None),
        ('learning_ai_attempts', None),
        ('learning_feedback', None),
        ('learning_publications', None),
        ('learning_draft_families', None),
        ('learning_settings', None),

        # Reading 模块
        ('reading_records', None),
        ('reading_vocabulary', None),
        ('reading_reviews', None),

        # Reflections 模块
        ('reflection_entries', None),
        ('reflection_versions', None),
        ('reflection_ai_attempts', None),
        ('reflection_operations', None),

        # Stocks 模块
        ('stock_records', None),

        # Errors 模块
        ('error_records', None),
        ('error_types', None),

        # Predictions 模块
        ('prediction_records', None),

        # Behavior 模块
        ('behavior_applications', None),

        # Behavior Report 模块
        ('behavior_reports', None),

        # Knowledge 模块
        ('knowledge_nodes', None),
        ('knowledge_links', None),
    ]

    # 迁移数据
    print("开始迁移数据...")
    print("-" * 60)
    total_rows = 0

    for table_name, columns in tables:
        count = migrate_table(sqlite_conn, pg_conn, table_name, columns)
        total_rows += count

    print("-" * 60)
    print(f"\n✅ 迁移完成！共迁移 {total_rows} 行数据")
    print()

    # 关闭连接
    sqlite_conn.close()
    pg_conn.close()

    print("=" * 60)
    print("提示：")
    print("1. 可以启动服务器验证数据是否正确")
    print("2. 如果一切正常，可以删除旧的 data.db 文件")
    print("3. 在另一台电脑上拉取代码即可使用云端数据库")
    print("=" * 60)

if __name__ == '__main__':
    main()
