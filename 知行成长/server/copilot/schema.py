"""Canonical course tables; migrations never drop learning records."""
TABLES = """
CREATE TABLE IF NOT EXISTS copilot_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS copilot_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS copilot_lessons (
    module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1,
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
    data TEXT NOT NULL, PRIMARY KEY(module_id,round_id,lesson_no));
CREATE TABLE IF NOT EXISTS copilot_drafts (
    id TEXT PRIMARY KEY, lesson_no INTEGER NOT NULL, version INTEGER NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS copilot_generation_attempts (
    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
    draft_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS copilot_operations (
    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS copilot_learning_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi',
    round_id INTEGER NOT NULL DEFAULT 1,
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
    completion_type TEXT NOT NULL CHECK(completion_type IN ('review', 'summary', 'quick', 'manual')),
    review_answers TEXT,
    summary_text TEXT,
    time_spent_seconds INTEGER,
    scroll_depth REAL,
    completed_at TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    UNIQUE(module_id, round_id, lesson_no));
"""

REVIEW_TABLES = """
CREATE TABLE IF NOT EXISTS copilot_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1,
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
    mastery_level TEXT NOT NULL CHECK(mastery_level IN ('fully_understood', 'basically_understood', 'partially_understood', 'not_understood')),
    value_rating INTEGER NOT NULL CHECK(value_rating BETWEEN 0 AND 3),
    feeling_tags TEXT, key_learnings TEXT, questions TEXT, next_direction TEXT,
    created_at TEXT NOT NULL, UNIQUE(module_id, round_id, lesson_no));
CREATE TABLE IF NOT EXISTS copilot_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL DEFAULT 'full_course', content TEXT NOT NULL,
    feedback_snapshot TEXT, created_at TEXT NOT NULL);
"""

TABLES += REVIEW_TABLES


def upgrade_learning_archive(connection):
    """Additive repair for stores already recorded as legacy-cloud-v3.

    Keep these columns out of legacy_schema.REQUIRED: a missing optional flag
    must never cause an otherwise valid learning table to be renamed/imported.
    """
    connection.execute('ALTER TABLE copilot_learning_records ADD COLUMN IF NOT EXISTS archived INTEGER NOT NULL DEFAULT 0')
    connection.execute('ALTER TABLE copilot_learning_records ADD COLUMN IF NOT EXISTS archived_at TEXT')
