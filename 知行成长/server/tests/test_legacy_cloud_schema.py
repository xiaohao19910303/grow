"""Migration runs only against a disposable localhost PostgreSQL schema."""
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import db
import psycopg2
from legacy_schema import migrate, columns


@unittest.skipUnless(os.getenv('TEST_LEGACY_PG_DSN'),'Requires isolated localhost PostgreSQL')
class PostgreSQLFixture(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['TEST_LEGACY_PG_DSN']
        if 'host=127.0.0.1' not in self.dsn:raise RuntimeError('localhost only')
        self.schema='legacy_cloud_'+uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('CREATE SCHEMA '+self.schema)
        original=db.connect
        self.mock=patch('db.connect',lambda *a,**kw:original(self.dsn+' options=-csearch_path='+self.schema,tenant=False))
        self.mock.start();self.addCleanup(self.mock.stop);self.addCleanup(self.drop)
    def drop(self):
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE')


class LegacySchemaTests(PostgreSQLFixture):
    def test_learning_archive_upgrade_is_additive_after_completed_migration(self):
        migrate()
        with db.connect() as c:
            c.execute("INSERT INTO copilot_learning_records(module_id,round_id,lesson_no,completion_type,summary_text,time_spent_seconds,completed_at,idempotency_key) VALUES ('renzhi',2,1,'summary','PRIVATE PRESERVED',90,'2026-10-19','archive-upgrade')")
            c.execute('ALTER TABLE copilot_learning_records DROP COLUMN IF EXISTS archived')
            c.execute('ALTER TABLE copilot_learning_records DROP COLUMN IF EXISTS archived_at')
        report = migrate()
        with db.connect() as c:
            record = dict(c.execute('SELECT * FROM copilot_learning_records').fetchone())
            self.assertEqual(record['archived'], 0)
            self.assertIsNone(record['archived_at'])
            self.assertEqual((record['round_id'], record['summary_text'], record['time_spent_seconds']),
                             (2, 'PRIVATE PRESERVED', 90))
            c.execute("UPDATE copilot_learning_records SET archived=1,archived_at='2026-10-20'")
        self.assertEqual(migrate(), report)
        with db.connect() as c:
            record = c.execute('SELECT archived,archived_at FROM copilot_learning_records').fetchone()
            self.assertEqual((record['archived'], record['archived_at']), (1, '2026-10-20'))

    def test_old_bootstrap_schemas_are_archived_and_imported_once(self):
        with db.connect() as c:c.executescript((Path(__file__).parent/'fixtures/legacy-bootstrap.sql').read_text())
        seeds={
            'behavior_applications':('app-old',{'date':'2026-10-16','module_id':'renzhi','concept':'保留概念','scenario':'PRIVATE SCENARIO'}),
            'error_types':('type-old',{'name':'误判','description':'PRIVATE TYPE'}),
            'error_records':('error-old',{'date':'2026-10-16','module_id':'renzhi','error_type':'误判','description':'PRIVATE ERROR'}),
            'behavior_reports':('report-old',{'date':'2026-10-16','period_days':30,'content':'PRIVATE REPORT'}),
            'reading_vocabulary':('vocab-old',{'word':'evidence','article_id':'article-old','next_review':'2026-10-17'}),
            'reading_reviews':('review-old',{'vocab_id':'vocab-old','feedback':'good','step_before':0,'step_after':1}),
            'copilot_drafts':('draft-old',{'lesson_no':3,'version':2,'status':'ready','content':'PRIVATE DRAFT'}),
            'knowledge_nodes':('node-old',{'name':'保留节点','category':'认知','summary':'SUMMARY','kind':'concept'}),
            'prediction_records':('prediction-old',{'date':'2026-10-16','statement':'PRIVATE PREDICTION','probability':60}),
        }
        with db.connect() as c:
            for table,(key,data) in seeds.items():c.execute(f'INSERT INTO {table} VALUES (?,?)',(key,json.dumps(data)))
            c.execute('INSERT INTO copilot_learning_records VALUES (?,?)',(1,json.dumps({'completed_at':'2026-10-16T10:00:00+08:00','summary_text':'PRIVATE SUMMARY'})))
            c.execute('INSERT INTO reflection_versions VALUES (?,?,?)',('ref-old',1,json.dumps({'raw_text':'PRIVATE REFLECTION'})))
            c.execute('INSERT INTO copilot_meta VALUES (?,?)',('plan_confirmation',json.dumps({'hash':'h','lessons':[1]})))
            c.execute('INSERT INTO copilot_settings VALUES (?,?)',('api_key','OLD_SECRET'))
        report=migrate()
        self.assertEqual(report['needs_review'],0,report)
        self.assertEqual(report['imported'],len(seeds)+3)
        self.assertEqual(report,migrate())
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT concept FROM behavior_applications').fetchone()[0],'保留概念')
            self.assertEqual(c.execute('SELECT data FROM behavior_applications__legacy_v3').fetchone()[0],json.dumps(seeds['behavior_applications'][1]))
            self.assertEqual(c.execute('SELECT summary_text FROM copilot_learning_records').fetchone()[0],'PRIVATE SUMMARY')
            self.assertEqual(c.execute('SELECT key FROM reflection_versions').fetchone()[0],'ref-old#1')
            self.assertEqual(c.execute("SELECT count(*) FROM copilot_settings__legacy_v3 WHERE id='api_key'").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM reading_reviews').fetchone()[0],1)
            c.execute("INSERT INTO behavior_applications(date,module_id,concept) VALUES ('2026-10-17','renzhi','NEW')")
            self.assertEqual(c.execute('SELECT count(DISTINCT id) FROM behavior_applications').fetchone()[0],2)
    def test_relations_and_nonserial_ids_survive_schema_conversion(self):
        with db.connect() as c:
            for table in ('error_records','knowledge_nodes','knowledge_links'):
                c.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY,data TEXT)')
            c.execute('INSERT INTO error_records VALUES (?,?)',('child',json.dumps({'date':'2026-10-16','module_id':'renzhi','error_type':'误判','description':'child','related_error_id':'parent'})))
            c.execute('INSERT INTO error_records VALUES (?,?)',('parent',json.dumps({'date':'2026-10-16','module_id':'renzhi','error_type':'误判','description':'parent'})))
            for key in ('a','b'):c.execute('INSERT INTO knowledge_nodes VALUES (?,?)',(key,json.dumps({'name':key,'category':'认知','kind':'concept'})))
            c.execute('INSERT INTO knowledge_links VALUES (?,?)',('link',json.dumps({'source_id':'a','target_id':'b','link_type':'related','weight':2})))
        report=migrate();self.assertEqual(report['needs_review'],0,report)
        with db.connect() as c:
            parent=c.execute("SELECT id FROM error_records WHERE description='parent'").fetchone()[0]
            self.assertEqual(c.execute("SELECT related_error_id FROM error_records WHERE description='child'").fetchone()[0],parent)
            self.assertEqual(c.execute('SELECT count(*) FROM knowledge_links l JOIN knowledge a ON a.id=l.source_id JOIN knowledge b ON b.id=l.target_id').fetchone()[0],1)

    def test_invalid_rows_are_preserved_and_reported_without_partial_ddl(self):
        with db.connect() as c:
            c.execute('CREATE TABLE behavior_applications(id TEXT PRIMARY KEY,data TEXT)')
            c.execute("INSERT INTO behavior_applications VALUES ('unknown','not-json')")
        report=migrate();self.assertEqual(report['needs_review'],1)
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT data FROM behavior_applications__legacy_v3').fetchone()[0],'not-json')
            self.assertEqual(c.execute('SELECT state FROM legacy_row_map').fetchone()[0],'needs_review')
            self.assertIn('concept',columns(c,'behavior_applications'))
