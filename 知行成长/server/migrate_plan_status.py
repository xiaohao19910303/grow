"""学习计划状态管理迁移脚本

为学习计划添加状态管理功能：
- status: active | paused | archived
- paused_at, resumed_at, archived_at: 状态变更时间戳
- plan_status_history: 状态变更历史记录表
"""
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import db


def migrate_plan_status():
    """执行学习计划状态管理迁移"""
    print("🚀 开始学习计划状态管理迁移...")

    conn = db.connect()

    try:
        # 1. 创建状态历史表
        print("📋 步骤 1/3: 创建 plan_status_history 表...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plan_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                reason TEXT,
                FOREIGN KEY (plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plan_status_plan_id ON plan_status_history(plan_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plan_status_changed_at ON plan_status_history(changed_at)")

        # 2. 为现有计划添加默认状态
        print("📋 步骤 2/3: 为现有计划添加默认状态...")
        plans = conn.execute("SELECT id, data FROM learning_plans").fetchall()
        count = 0
        for plan_row in plans:
            plan_id = plan_row[0]
            plan_data = json.loads(plan_row[1])

            # 如果没有 status 字段，添加默认值
            if 'status' not in plan_data:
                plan_data['status'] = 'active'
                plan_data['created_at'] = plan_data.get('created_at', datetime.now().isoformat())

                # 保存更新后的数据
                conn.execute(
                    "UPDATE learning_plans SET data = ? WHERE id = ?",
                    (json.dumps(plan_data, ensure_ascii=False), plan_id)
                )

                # 记录状态历史
                conn.execute(
                    """INSERT INTO plan_status_history (plan_id, from_status, to_status, changed_at, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (plan_id, None, 'active', plan_data['created_at'], '初始化')
                )
                count += 1

        print(f"✅ 为 {count} 个计划添加了默认状态")

        # 3. 验证迁移结果
        print("📋 步骤 3/3: 验证迁移结果...")
        total_plans = conn.execute("SELECT COUNT(*) FROM learning_plans").fetchone()[0]
        plans_with_status = conn.execute(
            "SELECT COUNT(*) FROM learning_plans WHERE data::jsonb->>'status' IS NOT NULL"
        ).fetchone()[0]
        status_records = conn.execute("SELECT COUNT(*) FROM plan_status_history").fetchone()[0]

        conn.commit()

        print(f"\n✅ 迁移完成！")
        print(f"   - 总计划数: {total_plans}")
        print(f"   - 已添加状态: {plans_with_status}")
        print(f"   - 状态历史记录: {status_records}")

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
        # 检查表是否存在（PostgreSQL 语法）
        tables = conn.execute(
            """SELECT tablename FROM pg_tables
               WHERE tablename = 'plan_status_history'"""
        ).fetchall()

        if not tables:
            print("❌ plan_status_history 表不存在")
            return False

        # 检查计划状态
        total = conn.execute("SELECT COUNT(*) FROM learning_plans").fetchone()[0]
        with_status = conn.execute(
            "SELECT COUNT(*) FROM learning_plans WHERE data::jsonb->>'status' IS NOT NULL"
        ).fetchone()[0]

        if total != with_status:
            print(f"⚠️ 警告: {total - with_status} 个计划缺少状态字段")
            return False

        # 检查状态分布
        status_dist = conn.execute("""
            SELECT data::jsonb->>'status' as status, COUNT(*) as count
            FROM learning_plans
            GROUP BY status
        """).fetchall()

        print("✅ 验证通过！")
        print(f"   - 总计划数: {total}")
        print(f"   - 状态分布:")
        for row in status_dist:
            print(f"     {row[0]}: {row[1]}")

        return True

    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="学习计划状态管理迁移")
    parser.add_argument("--verify", action="store_true", help="仅验证迁移结果")
    args = parser.parse_args()

    if args.verify:
        verify_migration()
    else:
        migrate_plan_status()
        verify_migration()
