"""Canonical dashboard tables shared by bootstrap and cloud migrations."""
TABLES = """
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS modules (
    id TEXT PRIMARY KEY, name TEXT, color TEXT, ord INTEGER
);
CREATE TABLE IF NOT EXISTS checkins (
    date TEXT, module_id TEXT, level INTEGER,
    PRIMARY KEY (date, module_id)
);
CREATE TABLE IF NOT EXISTS habits (
    date TEXT PRIMARY KEY, minutes INTEGER DEFAULT 0, note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS custom_fields (
    key TEXT PRIMARY KEY, label TEXT, type TEXT
);
CREATE TABLE IF NOT EXISTS custom_records (
    id SERIAL PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    date TEXT, title TEXT, context TEXT, options TEXT, reason TEXT,
    expected TEXT, probability INTEGER, emotion TEXT, actual TEXT, bias TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    date TEXT, statement TEXT, probability INTEGER, result TEXT, deviation TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    date TEXT, thought TEXT, actual TEXT, gap TEXT, action TEXT
);
CREATE TABLE IF NOT EXISTS insights (
    id SERIAL PRIMARY KEY,
    date TEXT, insight TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS knowledge (
    id SERIAL PRIMARY KEY,
    name TEXT, category TEXT, summary TEXT, source TEXT, kind TEXT,
    date TEXT DEFAULT ''
);
"""
