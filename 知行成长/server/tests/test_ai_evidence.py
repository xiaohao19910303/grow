"""账号内证据迁移、不可变输入、来源状态及隔离备份恢复。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import db
import ai_evidence as evidence
from copilot.core import Problem, encoded
from history_sources import record_source, teaching_source, availability
from tenancy import current_user
from test_legacy_cloud_schema import PostgreSQLFixture

MESSAGES=[{'role':'system','content':'只依据给定资料。'},
          {'role':'user','content':'PRIVATE SENT EXCERPT'}]


class EvidenceTests(PostgreSQLFixture):
    def capture(self, identity='task-one'):
        with db.connect() as c:
            return evidence.freeze(c,'reflection',identity,MESSAGES,'fixture',sources=evidence.inputs({'text':'PRIVATE SENT EXCERPT'}))

    def test_nested_inputs_are_frozen_and_same_task_cannot_be_replaced(self):
        original=copy.deepcopy(MESSAGES)
        with db.connect() as c:
            value=evidence.freeze(c,'reflection','task-one',original,'fixture')
        original[1]['content']='MUTATED'
        with db.connect() as c:
            saved=evidence.read(c,value['id'])
            self.assertEqual(saved['messages'],MESSAGES)
            self.assertEqual(evidence.freeze(c,'reflection','task-one',MESSAGES,'fixture')['id'],value['id'])
        with self.assertRaises(Problem),db.connect() as c:
            evidence.freeze(c,'reflection','task-one',original,'fixture')
        with db.connect() as c:self.assertEqual(evidence.read(c,value['id'])['messages'],MESSAGES)

    def test_invalid_or_newer_schema_is_preserved(self):
        self.capture()
        with db.connect() as c:c.execute("INSERT INTO ai_evidence_migrations VALUES (2,'future')")
        with self.assertRaises(Problem),db.connect() as c:evidence.initialize(c)
        with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM ai_evidence_snapshots').fetchone()[0],1)

    def test_orphan_schema_is_not_silently_adopted_or_dropped(self):
        with db.connect() as c:c.execute('CREATE TABLE ai_evidence_snapshots(id TEXT PRIMARY KEY,data TEXT)')
        with self.assertRaises(Problem),db.connect() as c:evidence.initialize(c)
        with db.connect() as c:self.assertTrue(evidence.exists(c,'ai_evidence_snapshots'));self.assertFalse(evidence.exists(c,'ai_evidence_migrations'))

    def test_source_edit_delete_and_missing_table_do_not_mutate_captured_input(self):
        with db.connect() as c:
            c.execute('CREATE TABLE reflection_entries(id TEXT PRIMARY KEY,data TEXT)')
            c.execute('INSERT INTO reflection_entries VALUES (?,?)',('ref-one',encoded({'raw_text':'PRIVATE ORIGINAL','version':1})))
            source=record_source(c,'reflection_entries',('ref-one',),'本人选定记录','PRIVATE SENT EXCERPT',fields=['raw_text'])
            value=evidence.freeze(c,'reflection','task-one',MESSAGES,'fixture',sources=[source])
            self.assertEqual(availability(c,source),'unchanged')
            c.execute('UPDATE reflection_entries SET data=?',(encoded({'raw_text':'EDITED','version':2}),))
            self.assertEqual(availability(c,source),'changed')
            c.execute('UPDATE reflection_entries SET data=?',(encoded({'raw_text':'PRIVATE ORIGINAL','archived':True}),))
            self.assertEqual(availability(c,source),'archived')
            c.execute('DELETE FROM reflection_entries');self.assertEqual(availability(c,source),'deleted')
            c.execute('DROP TABLE reflection_entries');self.assertEqual(availability(c,source),'unavailable')
            self.assertEqual(evidence.read(c,value['id'])['messages'],MESSAGES)

    def test_shared_snapshot_is_released_only_after_last_analysis_reference(self):
        value=self.capture()
        with db.connect() as c:
            evidence.bind(c,'reflection-result','result-one',value['id'])
            evidence.release(c,'reflection','task-one')
            self.assertEqual(evidence.read(c,value['id'])['messages'],MESSAGES)
            evidence.release(c,'reflection-result','result-one')
            self.assertEqual(c.execute('SELECT count(*) FROM ai_evidence_snapshots').fetchone()[0],0)

    def test_snapshot_and_links_roll_back_together_on_write_failure(self):
        with self.assertRaises(RuntimeError),db.connect() as c:
            evidence.freeze(c,'reflection','task-one',MESSAGES,'fixture')
            raise RuntimeError('simulated commit failure')
        with db.connect() as c:self.assertFalse(evidence.exists(c,'ai_evidence_snapshots'))

    def test_api_requires_identity_does_not_fabricate_legacy_and_respects_schema(self):
        value=self.capture()
        app=FastAPI();evidence.register(app)
        @app.exception_handler(Problem)
        async def problem(request,error):return JSONResponse({'error':error.code},status_code=error.status)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/ai/evidence/'+value['id']).status_code,401)
            token=current_user.set({'id':'fixture','schema_name':self.schema})
            try:
                response=client.get('/api/ai/evidence/'+value['id']);self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertEqual(response.json()['messages'],MESSAGES)
                legacy=client.get('/api/ai/evidence',params={'kind':'reflection','resource_id':'old'}).json()
                self.assertTrue(legacy['legacy']);self.assertEqual(legacy['items'],[])
                self.assertEqual(client.get('/api/ai/evidence',params={'kind':'arbitrary_table','resource_id':'x'}).status_code,422)
                # A different schema containing no evidence cannot see this account's snapshot.
                with patch('db.connect',lambda *a,**kw:db.CompatConnection(db.psycopg2.connect(self.dsn+' options=-csearch_path=pg_catalog'))):
                    self.assertEqual(client.get('/api/ai/evidence/'+value['id']).status_code,404)
            finally:current_user.reset(token)

    def test_tampered_input_hash_is_rejected_before_consumption(self):
        value=self.capture()
        value['messages'][1]['content']='TAMPERED'
        with db.connect() as c:c.execute('UPDATE ai_evidence_snapshots SET data=?',(encoded(value),))
        with self.assertRaises(Problem),db.connect() as c:evidence.read(c,value['id'])

    def test_private_schema_dump_restore_preserves_evidence_and_links(self):
        value=self.capture()
        with tempfile.TemporaryDirectory() as directory:
            dump=str(Path(directory)/'evidence.dump')
            subprocess.run(['pg_dump','--dbname='+self.dsn,'--schema='+self.schema,'--format=custom','--file='+dump],check=True,capture_output=True)
            # Only this test's disposable schema is replaced; no other schema/database is touched.
            with db.connect() as c:c.execute('DROP SCHEMA '+self.schema+' CASCADE')
            subprocess.run(['pg_restore','--dbname='+self.dsn,'--no-owner','--no-acl',dump],check=True,capture_output=True)
        with db.connect() as c:
            self.assertEqual(evidence.read(c,value['id'])['messages'],MESSAGES)
            self.assertEqual(evidence.linked(c,'reflection','task-one')[0]['id'],value['id'])

    def test_teaching_sources_use_registered_resolver_and_keep_excerpt_immutable(self):
        origin=teaching_source('study-lesson',['yingyu','lesson.md'],'上一课','SENT EXCERPT','version-one',truncated=True)
        current=['version-one'];resolvers={'study-lesson':lambda module,filename:current[0]}
        with db.connect() as c:
            value=evidence.freeze(c,'study','teaching-test',MESSAGES,'fixture',sources=[origin])
            self.assertEqual(availability(c,origin,resolvers=resolvers),'unchanged')
            current[0]='version-two';self.assertEqual(availability(c,origin,resolvers=resolvers),'changed')
            self.assertEqual(availability(c,origin),'unverifiable')
            self.assertTrue(evidence.read(c,value['id'])['sources'][0]['truncated'])
            self.assertEqual(evidence.read(c,value['id'])['messages'],MESSAGES)

    def test_publication_replay_cannot_replace_another_input(self):
        first=self.capture('first');second=self.capture('second')
        sql,params=evidence.link_statement('study-course','yingyu/one.md',first['id'])
        with db.connect() as c:
            c.execute(sql,params);c.execute(sql,params)
        with self.assertRaises(db.psycopg2.IntegrityError),db.connect() as c:
            sql,params=evidence.link_statement('study-course','yingyu/one.md',second['id'])
            c.execute(sql,params)
        with db.connect() as c:self.assertEqual(evidence.linked(c,'study-course','yingyu/one.md')[0]['id'],first['id'])
