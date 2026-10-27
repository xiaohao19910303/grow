"""Additive tables inside the existing authenticated account's PostgreSQL schema."""
TABLES = '''
CREATE TABLE IF NOT EXISTS investment_objects (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, version INTEGER NOT NULL,
    data TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS investment_objects_kind ON investment_objects(kind,created_at,id);
CREATE TABLE IF NOT EXISTS investment_versions (
    object_id TEXT NOT NULL REFERENCES investment_objects(id), version INTEGER NOT NULL,
    data TEXT NOT NULL, PRIMARY KEY(object_id,version)
);
CREATE TABLE IF NOT EXISTS investment_requests (
    request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investment_accounts (
    id TEXT PRIMARY KEY REFERENCES investment_objects(id), opening_cash NUMERIC(28,10) NOT NULL,
    baseline_date DATE NOT NULL
);
CREATE TABLE IF NOT EXISTS investment_fills (
    id TEXT PRIMARY KEY REFERENCES investment_objects(id), sequence BIGSERIAL UNIQUE,
    account_id TEXT NOT NULL REFERENCES investment_accounts(id),
    instrument_id TEXT NOT NULL REFERENCES investment_objects(id),
    side TEXT NOT NULL CHECK(side IN ('buy','sell')), price NUMERIC(28,10) NOT NULL CHECK(price>0),
    quantity NUMERIC(28,10) NOT NULL CHECK(quantity>0), fee NUMERIC(28,10), tax NUMERIC(28,10),
    executed_at TIMESTAMPTZ NOT NULL, source TEXT NOT NULL, external_id TEXT,
    UNIQUE(account_id,source,external_id)
);
CREATE TABLE IF NOT EXISTS investment_cash_events (
    id TEXT PRIMARY KEY REFERENCES investment_objects(id),
    account_id TEXT NOT NULL REFERENCES investment_accounts(id),
    kind TEXT NOT NULL, amount NUMERIC(28,10) NOT NULL CHECK(amount>0), occurred_at TIMESTAMPTZ NOT NULL
);
CREATE OR REPLACE VIEW investment_discovery AS
SELECT id,jsonb_build_object('title',CASE kind WHEN 'reviews' THEN '投资复盘'
    WHEN 'trade-plans' THEN '投资条件计划' WHEN 'dossiers' THEN '投资研究' ELSE '投资规则试验' END,
    'date',COALESCE(data::jsonb->>'date',to_char(updated_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD')),
    'record_kind',kind,'account_id',data::jsonb->>'account_id',
    'summary','私有投资记录；进入投资工作台查看本人资料。')::text AS data
FROM investment_objects WHERE kind IN ('reviews','trade-plans','dossiers','principles');
'''
