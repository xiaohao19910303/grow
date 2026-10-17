"""Read-only SQLite sources and transactionally archived remote imports."""
import json
import sqlite3
import tempfile
from pathlib import Path

import db
from legacy_schema import migrate
from legacy_sqlite import preview, apply
from copilot.core import Problem
from test_legacy_cloud_schema import PostgreSQLFixture


class SQLiteImportTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();migrate()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'old.db'
        with sqlite3.connect(self.source) as c:
            c.executescript('CREATE TABLE reviews(id INTEGER PRIMARY KEY,date TEXT,thought TEXT,actual TEXT,gap TEXT,action TEXT); CREATE TABLE reading_records(id TEXT PRIMARY KEY,data TEXT); CREATE TABLE copilot_settings(key TEXT PRIMARY KEY,value TEXT);')
            c.execute("INSERT INTO reviews VALUES (1,'2026-10-16','PRIVATE ORIGINAL','a','g','n')")
            c.execute('INSERT INTO reading_records VALUES (?,?)',('article-old',json.dumps({'type':'article','title':'PRIVATE SOURCE'})))
            c.execute("INSERT INTO copilot_settings VALUES ('api_key','NEVER_IMPORT_TEST_KEY')")
    def test_missing_records_import_and_original_source_is_unchanged(self):
        original=self.source.read_bytes();report=preview(self.source);result=apply(self.source,report['token'])
        self.assertEqual(result['imported'],2,result)
        self.assertEqual(result['archived'],2)
        self.assertEqual(original,self.source.read_bytes())
        self.assertEqual(result,apply(self.source,report['token']))
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT thought FROM reviews').fetchone()[0],'PRIVATE ORIGINAL')
            raw=''.join(r[0] for r in c.execute('SELECT raw FROM sqlite_source_rows'))
            self.assertNotIn('NEVER_IMPORT_TEST_KEY',raw)
            c.execute("INSERT INTO reviews(date,thought) VALUES ('2026-10-17','NEW')")
            self.assertEqual(c.execute('SELECT COUNT(DISTINCT id) FROM reviews').fetchone()[0],2)
    def test_existing_remote_records_win_and_local_variant_remains_archived(self):
        with db.connect() as c:c.execute("INSERT INTO reviews VALUES (1,'2026-10-16','PRIVATE REMOTE','a','g','n')")
        report=preview(self.source);result=apply(self.source,report['token'])
        self.assertEqual(result['counts']['retained_remote'],1)
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT thought FROM reviews').fetchone()[0],'PRIVATE REMOTE')
            self.assertIn('PRIVATE ORIGINAL',c.execute("SELECT raw FROM sqlite_source_rows WHERE source_table='reviews'").fetchone()[0])
    def test_changed_source_rejects_stale_preview(self):
        report=preview(self.source)
        with sqlite3.connect(self.source) as c:c.execute("UPDATE reviews SET thought='changed'")
        with self.assertRaises(Problem):apply(self.source,report['token'])
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],0)
