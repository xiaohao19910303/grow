"""Upgrade known legacy PostgreSQL layouts without discarding original tables."""
import sqlite3
from copilot.core import fail
from behavior.store import TABLE_SQL as BEHAVIOR
from behavior_report.store import TABLE_SQL as REPORTS
from errors.store import TABLE_SQL as ERRORS
from knowledge.store import TABLE_SQL as KNOWLEDGE

COPILOT = {
    'copilot_drafts': ('id lesson_no version status data updated_at', 'id TEXT PRIMARY KEY, lesson_no INTEGER NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL'),
    'copilot_generation_attempts': ('id request_key request_hash draft_id status data', 'id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, draft_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL'),
    'copilot_operations': ('id request_key request_hash status data created_at', 'id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL'),
    'copilot_lessons': ('module_id round_id lesson_no data', "module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1, lesson_no INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(module_id,round_id,lesson_no)"),
    'copilot_learning_records': ('id module_id round_id lesson_no completion_type review_answers summary_text time_spent_seconds scroll_depth completed_at idempotency_key', "id SERIAL PRIMARY KEY, module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1, lesson_no INTEGER NOT NULL, completion_type TEXT NOT NULL, review_answers TEXT, summary_text TEXT, time_spent_seconds INTEGER, scroll_depth REAL, completed_at TEXT NOT NULL, idempotency_key TEXT UNIQUE, UNIQUE(module_id,round_id,lesson_no)"),
}
TARGETS = {
    'behavior_applications': ('id date module_id concept scenario effectiveness created_at', BEHAVIOR),
    'behavior_reports': ('id date period_days content data_summary created_at', REPORTS),
    'error_records': ('id date module_id error_type description severity context improvement_action is_repeat related_error_id created_at', ERRORS),
    'knowledge_links': ('id source_id target_id link_type weight', KNOWLEDGE),
    **{name: (columns, f'CREATE TABLE {name} ({definition});') for name, (columns, definition) in COPILOT.items()},
}


def columns(c, table):
    return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,))}


def migrate(c):
    if isinstance(c, sqlite3.Connection): return []
    c.execute("SELECT pg_advisory_xact_lock(hashtext('grow-legacy-schema-v1'))")
    changed = []
    for table in ('copilot_settings', 'copilot_meta'):
        if columns(c, table) == {'id', 'data'}:
            c.execute(f'ALTER TABLE {table} RENAME COLUMN id TO key')
            c.execute(f'ALTER TABLE {table} RENAME COLUMN data TO value')
            changed.append(table)
    for table, (expected, ddl) in TARGETS.items():
        current = columns(c, table)
        if not current or set(expected.split()) <= current: continue
        if current not in ({'id', 'data'}, {'lesson_no', 'data'}):
            fail('legacy_schema_migration', f'{table} 的旧表结构未识别，已保留原表，请先完成数据迁移。', 503)
        c.execute(f'LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE')
        if c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
            fail('legacy_schema_migration', f'{table} 含旧记录，已保留原表，请先完成数据迁移。', 503)
        archive = table+'_before_pg_v1'
        if columns(c, archive):
            fail('legacy_schema_migration', f'{table} 已有迁移归档，请人工核对后恢复。', 503)
        c.execute(f'ALTER TABLE {table} RENAME TO {archive}')
        c.executescript(ddl)
        changed.append(table)
    return changed
