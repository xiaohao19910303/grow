"""Offline stable-ID upgrade/verification for one selected PostgreSQL schema.

Normal startup upgrades each account through legacy_schema/store.
This command never deletes nodes or replaces existing identities.
"""
import argparse
import db
from psycopg2 import sql
from knowledge.schema import upgrade_stable_ids, verify_stable_ids


def select_schema(conn, schema):
    if schema is not None:
        exists = conn.execute('SELECT 1 FROM pg_namespace WHERE nspname=?', (schema,)).fetchone()
        if not exists:
            raise ValueError('指定的 schema 不存在。')
        conn._conn.cursor().execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
    return conn.execute('SELECT current_schema()').fetchone()[0]


def migrate_knowledge_stable_ids(schema=None):
    with db.connect() as conn:
        selected = select_schema(conn, schema)
        upgrade_stable_ids(conn)
        if not verify_stable_ids(conn):
            raise ValueError('稳定 ID 迁移验证失败，已回滚。')
    print(f'稳定 ID 迁移完成：schema={selected}，原节点及关系保留。')


def verify_migration(schema=None):
    with db.connect() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        selected = select_schema(conn, schema)
        valid = verify_stable_ids(conn)
    print(f'schema={selected}：' + ('稳定 ID 验证通过。' if valid else '稳定 ID 验证未通过，请核对列、唯一索引、默认值与记录。'))
    return valid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='只读验证，失败时退出码为 1')
    parser.add_argument('--schema', help='精确选择已有账号 schema；省略时使用连接当前 schema')
    args = parser.parse_args()
    try:
        if not args.verify:
            migrate_knowledge_stable_ids(args.schema)
        return 0 if verify_migration(args.schema) else 1
    except (ValueError, db.psycopg2.Error):
        print('稳定 ID 检查或迁移失败，请核对目标 schema、表结构及重复 ID；未提交的修改已回滚。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
