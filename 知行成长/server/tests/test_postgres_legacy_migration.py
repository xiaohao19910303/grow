"""Reproduce the production legacy id/data tables in disposable PostgreSQL schemas."""
import os,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import db,psycopg2

@unittest.skipUnless(os.getenv('TEST_GITHUB_PG_DSN'),'Requires local PostgreSQL')
class LegacyMigration(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['TEST_GITHUB_PG_DSN'];assert 'host=127.0.0.1' in self.dsn
        self.schema='legacy_test_'+uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('CREATE SCHEMA '+self.schema)
        self.connect=db.connect
        self.scoped=lambda *a,**k:self.connect(self.dsn+' options=-csearch_path='+self.schema)
        self.patch=patch('db.connect',self.scoped);self.patch.start()
        with self.scoped() as c:
            c.execute('CREATE TABLE knowledge (id SERIAL PRIMARY KEY,name TEXT)')
            for t in ('behavior_applications','behavior_reports','error_records','knowledge_links','copilot_settings','copilot_drafts','copilot_generation_attempts'):
                c.execute('CREATE TABLE '+t+' (id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            c.execute('CREATE TABLE copilot_learning_records (lesson_no INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            c.execute("INSERT INTO copilot_settings VALUES ('generation_total_timeout_seconds','300')")
    def tearDown(self):
        self.patch.stop()
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE')
    def test_known_old_tables_migrate_and_repeated_startup_preserves_records(self):
        from legacy_migrations import migrate
        with self.scoped() as c:migrate(c)
        from behavior.store import BehaviorStore
        from errors.store import ErrorStore
        from behavior_report.store import BehaviorReportStore
        from knowledge.store import KnowledgeGraphStore
        behavior=BehaviorStore(Path('/unused'));errors=ErrorStore(Path('/unused'))
        for store in (behavior,errors,BehaviorReportStore(Path('/unused')),KnowledgeGraphStore(Path('/unused'))):store.initialize()
        record=behavior.create('2026-10-17','renzhi','sample concept')
        self.assertIsInstance(record['id'],int)
        with self.scoped() as c:
            self.assertEqual(c.execute("SELECT value FROM copilot_settings WHERE key='generation_total_timeout_seconds'").fetchone()[0],'300')
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_applications_before_pg_v1').fetchone()[0],0)
            migrate(c)
        errors.initialize() # Previously duplicate seeds aborted the PostgreSQL transaction.
        self.assertEqual(behavior.list()[0]['id'],record['id'])
    def test_old_course_can_initialize_against_postgres_with_local_fixture(self):
        import shutil,tempfile
        from legacy_migrations import migrate
        from copilot.core import Store,MODULE
        with self.scoped() as c:migrate(c)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'PLAN_CONTENT_BACKEND':'local'}):
            root=Path(tmp);shutil.copytree(Path(__file__).parent/'fixtures/renzhi',root/MODULE)
            store=Store(root,root/'runtime')
            store.initialize()
            self.assertEqual(store.scan()['generated_count'],2)
            store.initialize()
            self.assertEqual(store.scan()['generated_count'],2)
    def test_ambiguous_nonempty_old_table_is_preserved(self):
        from legacy_migrations import migrate
        with self.scoped() as c:c.execute("INSERT INTO behavior_applications VALUES ('old-id','opaque legacy content')")
        with self.assertRaises(Exception):
            with self.scoped() as c:migrate(c)
        with self.scoped() as c:
            self.assertEqual(c.execute('SELECT data FROM behavior_applications').fetchone()[0],'opaque legacy content')
