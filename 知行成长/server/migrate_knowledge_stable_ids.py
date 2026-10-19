"""知识图谱 ID 稳定性迁移脚本

为知识图谱添加稳定 ID 支持：
- stable_id: UUID 格式的稳定标识符
- source_hash: 内容哈希（用于幂等导入）
- source_path: 来源路径（用于幂等导入）
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db


def migrate_knowledge_stable_ids():
    """执行知识图谱 ID 稳定性迁移"""
    print("🚀 开始知识图谱 ID 稳定性迁移...")

    conn = db.connect()

    try:
        # 1. 添加新列
        print("📋 步骤 1/4: 添加 stable_id 列...")
        conn.execute("""
            ALTER TABLE knowledge
            ADD COLUMN IF NOT EXISTS stable_id TEXT
        """)

        print("📋 步骤 2/4: 添加 source_hash 列...")
        conn.execute("""
            ALTER TABLE knowledge
            ADD COLUMN IF NOT EXISTS source_hash TEXT
        """)

        print("📋 步骤 3/4: 添加 source_path 列...")
        conn.execute("""
            ALTER TABLE knowledge
            ADD COLUMN IF NOT EXISTS source_path TEXT
        """)

        # 2. 为现有记录生成 stable_id
        print("📋 步骤 4/4: 为现有知识生成 stable_id...")
        records = conn.execute("SELECT id, stable_id FROM knowledge").fetchall()
        count = 0
        for record in records:
            record_id = record[0]
            stable_id = record[1]

            # 如果没有 stable_id，生成一个
            if not stable_id:
                new_stable_id = str(uuid.uuid4())
                conn.execute(
                    "UPDATE knowledge SET stable_id = ? WHERE id = ?",
                    (new_stable_id, record_id)
                )
                count += 1

        print(f"✅ 为 {count} 条现有知识生成了 stable_id")

        # 3. 创建索引
        print("\n📋 创建索引...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_stable_id
            ON knowledge(stable_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_source
            ON knowledge(source_path, source_hash)
        """)

        conn.commit()

        # 4. 验证迁移结果
        print("\n📋 验证迁移结果...")
        total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        with_stable_id = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE stable_id IS NOT NULL"
        ).fetchone()[0]

        print(f"\n✅ 迁移完成！")
        print(f"   - 总知识数: {total}")
        print(f"   - 已添加 stable_id: {with_stable_id}")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 迁移失败: {e}")
        raise
    finally:
        conn.close()


def verify_migration():
    """验证迁移结果"""
    print("\n🔍 验证迁移结果...")

    conn = db.connect()
    try:
        # 检查列是否存在（PostgreSQL 语法）
        columns = conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'knowledge'"""
        ).fetchall()
        column_names = [col[0] for col in columns]

        required_columns = ['stable_id', 'source_hash', 'source_path']
        missing = [col for col in required_columns if col not in column_names]

        if missing:
            print(f"❌ 缺少列: {', '.join(missing)}")
            return False

        # 检查索引
        indexes = conn.execute(
            """SELECT indexname FROM pg_indexes
               WHERE tablename = 'knowledge'"""
        ).fetchall()
        index_names = [idx[0] for idx in indexes]

        required_indexes = ['idx_knowledge_stable_id', 'idx_knowledge_source']
        missing_indexes = [idx for idx in required_indexes if idx not in index_names]

        if missing_indexes:
            print(f"⚠️ 缺少索引: {', '.join(missing_indexes)}")
            return False

        # 检查数据
        total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        with_stable_id = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE stable_id IS NOT NULL"
        ).fetchone()[0]

        if total != with_stable_id:
            print(f"⚠️ 警告: {total - with_stable_id} 条记录缺少 stable_id")
            return False

        print("✅ 验证通过！")
        print(f"   - 总知识数: {total}")
        print(f"   - 所有记录都有 stable_id")
        print(f"   - 索引已创建")

        return True

    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="知识图谱 ID 稳定性迁移")
    parser.add_argument("--verify", action="store_true", help="仅验证迁移结果")
    args = parser.parse_args()

    if args.verify:
        verify_migration()
    else:
        migrate_knowledge_stable_ids()
        verify_migration()
