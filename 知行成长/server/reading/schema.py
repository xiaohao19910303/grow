"""Canonical reading metadata and spaced review tables."""
TABLES = """
CREATE TABLE IF NOT EXISTS reading_records (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reading_vocabulary (
                    id TEXT PRIMARY KEY, word TEXT NOT NULL, normalized TEXT NOT NULL,
                    article_id TEXT, source_version INTEGER DEFAULT 1,
                    context_sentence TEXT, contextual_meaning TEXT,
                    part_of_speech TEXT, pronunciation TEXT,
                    step INTEGER DEFAULT 0, next_review TEXT,
                    paused INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
                    created_at TEXT, updated_at TEXT, data TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_vocab_word ON reading_vocabulary(normalized);
CREATE INDEX IF NOT EXISTS idx_vocab_review ON reading_vocabulary(next_review) WHERE paused=0 AND archived=0;
CREATE TABLE IF NOT EXISTS reading_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vocab_id TEXT NOT NULL, feedback TEXT NOT NULL,
                    step_before INTEGER, step_after INTEGER,
                    reviewed_at TEXT,
                    FOREIGN KEY (vocab_id) REFERENCES reading_vocabulary(id));
CREATE INDEX IF NOT EXISTS idx_review_vocab ON reading_reviews(vocab_id)
"""
