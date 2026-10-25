"""Add stable identities to the current tenant without replacing graph nodes."""


def upgrade_stable_ids(conn):
    """Run in the caller's transaction; retain numeric IDs and existing UUIDs."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':knowledge-schema',0))")
    conn.execute('ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS stable_id TEXT')
    conn.execute('ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS source_path TEXT')
    conn.execute('ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS source_hash TEXT')
    conn.execute("ALTER TABLE knowledge ALTER COLUMN stable_id SET DEFAULT gen_random_uuid()::text")
    conn.execute("UPDATE knowledge SET stable_id=gen_random_uuid()::text WHERE stable_id IS NULL OR btrim(stable_id)=''")
    # Also upgrades installations with the old non-unique stable-ID index.
    # Conflicting existing IDs abort the transaction instead of renaming nodes.
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_stable_id ON knowledge(stable_id)')
    conn.execute('ALTER TABLE knowledge ALTER COLUMN stable_id SET NOT NULL')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source_path,source_hash)')


def verify_stable_ids(conn):
    """Read-only verification of this connection's schema, including future writes."""
    columns = {r['column_name']: r for r in conn.execute("""SELECT column_name,is_nullable,column_default
        FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='knowledge'""")}
    if not {'stable_id', 'source_path', 'source_hash'} <= columns.keys():
        return False
    stable = columns['stable_id']
    if stable['is_nullable'] != 'NO' or 'gen_random_uuid()' not in (stable['column_default'] or ''):
        return False
    unique = conn.execute("""SELECT 1 FROM pg_index i
        JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_attribute a ON a.attrelid=t.oid AND a.attname='stable_id'
        WHERE n.nspname=current_schema() AND t.relname='knowledge'
          AND i.indisunique AND i.indisvalid AND i.indnkeyatts=1
          AND i.indkey[0]=a.attnum AND i.indpred IS NULL AND i.indexprs IS NULL""").fetchone()
    if not unique:
        return False
    return conn.execute("SELECT COUNT(*) FROM knowledge WHERE stable_id IS NULL OR btrim(stable_id)=''").fetchone()[0] == 0
