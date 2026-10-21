"""Versioned, additive PostgreSQL migrations in the current private schema."""
from copilot.core import fail

SCHEMA_VERSION = 1
BUSINESS_TABLES = (
    'action_rhythm_preferences', 'action_focus_days', 'action_weekly_cards',
    'action_rhythm_events', 'action_rhythm_enrollments',
)

MIGRATION_1 = '''
CREATE TABLE IF NOT EXISTS action_rhythm_preferences (
    id TEXT PRIMARY KEY,
    effective_from DATE NOT NULL UNIQUE,
    data TEXT NOT NULL CHECK (jsonb_typeof(data::jsonb) = 'object'),
    revision INTEGER NOT NULL CHECK (revision > 0)
);
CREATE TABLE IF NOT EXISTS action_focus_days (
    id TEXT PRIMARY KEY,
    local_date DATE NOT NULL UNIQUE,
    data TEXT NOT NULL CHECK (jsonb_typeof(data::jsonb) = 'object'),
    revision INTEGER NOT NULL CHECK (revision > 0)
);
CREATE INDEX IF NOT EXISTS action_focus_plan ON action_focus_days ((data::jsonb->>'plan_id'));
CREATE TABLE IF NOT EXISTS action_weekly_cards (
    id TEXT PRIMARY KEY,
    week_start DATE NOT NULL UNIQUE CHECK (EXTRACT(ISODOW FROM week_start) = 1),
    data TEXT NOT NULL CHECK (jsonb_typeof(data::jsonb) = 'object'),
    revision INTEGER NOT NULL CHECK (revision > 0)
);
CREATE TABLE IF NOT EXISTS action_rhythm_events (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL CHECK (event_name IN (
        'rhythm_enrolled', 'focus_selected', 'execution_started',
        'activity_confirmed', 'activity_reversed', 'recap_saved',
        'minimum_selected', 'rest_selected', 'weekly_card_viewed',
        'weekly_card_confirmed', 'adjustment_linked', 'form_finished',
        'rhythm_survey_saved', 'rhythm_reminder_claimed'
    )),
    occurred_at TIMESTAMPTZ NOT NULL,
    data TEXT NOT NULL CHECK (jsonb_typeof(data::jsonb) = 'object')
);
CREATE INDEX IF NOT EXISTS action_rhythm_events_time ON action_rhythm_events (occurred_at);
CREATE INDEX IF NOT EXISTS action_rhythm_events_kind_time ON action_rhythm_events (event_name, occurred_at);
CREATE TABLE IF NOT EXISTS action_rhythm_enrollments (
    id TEXT PRIMARY KEY,
    experiment_key TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL CHECK (jsonb_typeof(data::jsonb) = 'object')
);
'''


def initialize(connection):
    """Run inside the caller's transaction; failure rolls back DDL and marker.

    There is no process-wide readiness cache: an existing account with legacy
    action tables still needs this migration after a deploy. The schema-scoped
    lock also serializes first requests handled by different server processes.
    """
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':rhythm-schema',0))")
    connection.execute('''CREATE TABLE IF NOT EXISTS action_rhythm_migrations (
        version INTEGER PRIMARY KEY CHECK (version > 0),
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    versions = [r[0] for r in connection.execute('SELECT version FROM action_rhythm_migrations ORDER BY version')]
    if any(version > SCHEMA_VERSION for version in versions):
        fail('CONTRACT_UPGRADE_REQUIRED', '日常节奏数据版本更新，请升级服务；已有数据保留。', 409)
    if 1 not in versions:
        if any(connection.execute('SELECT to_regclass(?)', (table,)).fetchone()[0]
               for table in BUSINESS_TABLES):
            fail('RHYTHM_SCHEMA_INCOMPLETE', '已有未标记版本的节奏表，请先核对；原表未改写。', 503)
        connection.executescript(MIGRATION_1)
        connection.execute('INSERT INTO action_rhythm_migrations(version) VALUES (1)')
    for table in BUSINESS_TABLES:
        if connection.execute('SELECT to_regclass(?)', (table,)).fetchone()[0] is None:
            fail('RHYTHM_SCHEMA_INCOMPLETE', '日常节奏数据表不完整，请核对迁移；未自动重建或清空。', 503)
    return {'schema_version': SCHEMA_VERSION}
