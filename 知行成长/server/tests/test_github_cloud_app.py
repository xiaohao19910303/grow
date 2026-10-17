"""Boot the real application with isolated PostgreSQL and an HTTP GitHub simulator."""
import importlib
import json
from pathlib import Path
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import db
import httpx
import psycopg2
from fastapi.testclient import TestClient
from plans.github import GitHubContent
from cloud_content import ModuleContent
from plans.github_store import GitHubPlans
from test_github_plans import Repository, B, D, S, content


@unittest.skipUnless(os.getenv('TEST_GITHUB_PG_DSN'), 'Requires isolated local PostgreSQL')
class CloudApplication(unittest.TestCase):
    def test_real_application_boot_and_publication(self):
        dsn = os.environ['TEST_GITHUB_PG_DSN']
        if 'host=127.0.0.1' not in dsn:raise RuntimeError('Only localhost is allowed')
        schema = 'cloud_app_test_'+uuid.uuid4().hex
        c = psycopg2.connect(dsn); c.autocommit = True
        c.cursor().execute('CREATE SCHEMA '+schema); c.close()
        repository = Repository()
        original = db.connect
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'CLOUD_DEPLOY':'1', 'PLAN_CONTENT_BACKEND':'github', 'RUNTIME_ROOT':tmp+'/runtime',
                'LEARN_ROOT':tmp+'/materials', 'APP_USERNAME':'owner', 'APP_PASSWORD':'CLOUD-TEST-PASSWORD-24-CHARACTERS',
                'RENDER_GIT_COMMIT':'test-deploy-revision'}), \
                patch('db.connect', lambda *a, **kw: original(dsn+' options=-csearch_path='+schema)), \
                patch('cloud_content.configured_content', side_effect=lambda: ModuleContent('owner/courses','main','TEST_ONLY_TOKEN',transport=httpx.MockTransport(repository))), \
                patch('plans.api.make_store', side_effect=lambda root, runtime: GitHubPlans(root,runtime,
                    GitHubContent('owner/courses','main','TEST_ONLY_TOKEN',transport=httpx.MockTransport(repository)))):
                spec=importlib.util.spec_from_file_location('isolated_cloud_app',Path(__file__).resolve().parents[1]/'app.py')
                dashboard=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(dashboard)
                dashboard.PENDING_SYNC_FILE = dashboard.DB_PATH/'no-pending-sync.json'
                with dashboard.get_conn() as old:
                    old.execute('CREATE TABLE copilot_settings (key TEXT PRIMARY KEY,value TEXT)')
                    old.execute("INSERT INTO copilot_settings VALUES ('api_key','OLD_TEST_SECRET')")
                with TestClient(dashboard.app, base_url='https://cloud.example', client=('198.51.100.1',1234)) as client:
                    with dashboard.get_conn() as old:
                        self.assertEqual(old.execute("SELECT count(*) FROM copilot_settings WHERE key='api_key'").fetchone()[0],0)
                    health=client.get('/api/health')
                    self.assertEqual(health.status_code,200)
                    self.assertEqual(health.json(),{'ok':True,'revision':'test-deploy-revision',
                                                   'plan_storage':'github','learning_plans_ready':True})
                    self.assertEqual(client.get('/').status_code,401)
                    client.auth=('owner',os.environ['APP_PASSWORD'])
                    for endpoint in ('/api/data', '/api/reflections', '/api/behavior/stats', '/api/errors/stats', '/api/stocks'):
                        response = client.get(endpoint)
                        self.assertEqual(response.status_code, 200, (endpoint, response.text))
                    state = client.get('/api/data').json()
                    stale = json.loads(json.dumps(state))
                    state['reviews'] = [{'date':'2026-10-17','thought':'PRIVATE REVIEW'}]
                    state['customRecords'] = [{'_client_id':'new-record','value':'private custom'}]
                    headers = {'X-Legacy-State-Protocol':'1'}
                    saved = client.put('/api/data', json=state, headers=headers)
                    self.assertEqual(saved.status_code,200,saved.text)
                    saved_state = saved.json()['state']
                    self.assertIsInstance(saved_state['reviews'][0]['id'],int)
                    self.assertIsInstance(saved.json()['assigned_ids']['customRecords']['new-record'],int)
                    self.assertEqual(client.put('/api/data',json=stale,headers=headers).status_code,409)
                    review_id = saved_state['reviews'][0]['id']
                    saved_state['reviews'][0]['thought'] = 'PRIVATE EDIT'
                    self.assertEqual(client.put('/api/data',json=saved_state,headers=headers).status_code,200)
                    self.assertEqual(client.get('/api/data').json()['reviews'][0]['id'], review_id)
                    h = {'X-Copilot-Request':'1'}
                    r = client.post('/api/reflections', json={'record_date':'2026-10-17','raw_text':'PRIVATE REFLECTION','key':'create-reflection'},headers=h)
                    self.assertEqual(r.status_code,200,r.text)
                    entry_id = r.json()['id']
                    r = client.put('/api/reflections/'+entry_id, json={'base_version':1,'record_date':'2026-10-17','raw_text':'PRIVATE EDITED REFLECTION','key':'update-reflection'},headers=h)
                    self.assertEqual(r.status_code,200,r.text)
                    calls = []
                    async def reflection_model(messages, cfg):
                        calls.append(cfg['key'])
                        yield {'text':json.dumps({'sections':[{'kind':'event','text':'建议整理','basis':'statement'}]})}
                        yield {'done':True}
                    dashboard.reflections_assistant.transport = reflection_model
                    ai = {'api_base_url':'https://user-model.example/v1','api_key':'REQUEST_ONLY_SECRET','model_name':'user-model'}
                    r = client.post('/api/reflections/'+entry_id+'/assist',json={'kind':'organize','snapshot':{'text':'PRIVATE EDITED REFLECTION'},'key':'assist-reflection','ai_config':ai},headers=h)
                    self.assertEqual(r.status_code,200,r.text)
                    import time
                    for _ in range(100):
                        attempt = client.get('/api/reflections/attempts/assist-reflection').json()
                        if attempt['status'] not in ('queued','generating'):break
                        time.sleep(.01)
                    self.assertEqual(attempt['status'],'ready',attempt)
                    self.assertEqual(calls,['REQUEST_ONLY_SECRET'])
                    self.assertNotIn('REQUEST_ONLY_SECRET',json.dumps(attempt))
                    from reflections.store import ReflectionsStore
                    fresh = ReflectionsStore(tmp+'/another-missing-directory',tmp+'/another-runtime')
                    fresh.initialize()
                    self.assertEqual(fresh.entry(entry_id)['raw_text'],'PRIVATE EDITED REFLECTION')
                    self.assertEqual(len(fresh.versions(entry_id)),2)
                    self.assertFalse(Path(tmp+'/materials').exists())
                    self.assertFalse(fresh.mirror_status(entry_id)['conflict'])
                    created = client.post('/api/behavior/applications',json={'date':'2026-10-17','module_id':'renzhi','concept':'复核证据'})
                    self.assertEqual(created.status_code,201,created.text)
                    self.assertIsInstance(created.json()['id'],int)
                    storage = client.get('/api/storage-status').json()
                    self.assertTrue(storage['modules']['reflections']['ready'])
                    self.assertTrue(storage['modules']['reading']['ready'])
                    self.assertTrue(storage['modules']['copilot']['ready'])
                    self.assertIsNone(storage['modules']['reading']['reason'])
                    listing=client.get('/api/plans')
                    self.assertEqual(listing.status_code,200,listing.text)
                    def post(path, data):
                        r=client.post('/api/plans'+path,json={'data':data},headers={'X-Copilot-Request':'1'})
                        self.assertEqual(r.status_code,200,r.text);return r.json()
                    draft=post('/drafts',{'brief':B,'document':D})
                    pid=post('/drafts/'+draft['id']+'/adopt',{'key':'adopt','expected_hash':draft['content_hash']})['plan_id']
                    post('/'+pid+'/sources',{'entries':S})
                    store=dashboard.plans_store;ctx=store.course_context(pid)
                    course=store.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
                    post('/drafts/'+course['id']+'/publish',{'key':'course','expected_hash':course['content_hash']})
                    r=client.get('/api/plans/'+pid+'/lessons/1')
                    self.assertEqual(r.status_code,200,r.text)
                    self.assertIn('核心概念',r.json()['content'])
                    # Reproduce the earlier create_tables.py layout in this disposable schema.
                    with dashboard.get_conn() as incompatible:
                        incompatible.execute('DROP TABLE behavior_applications')
                        incompatible.execute('CREATE TABLE behavior_applications (id TEXT PRIMARY KEY,data TEXT NOT NULL)')
                        incompatible.execute("INSERT INTO behavior_applications VALUES ('legacy-id','PRIVATE LEGACY RECORD')")
                    try:
                        dashboard.behavior_store.initialize()
                    except psycopg2.Error as exc:
                        dashboard.behavior_store.startup_error = exc
                    self.assertIsNotNone(dashboard.behavior_store.startup_error)
                    self.assertEqual(client.get('/api/behavior/applications').status_code,503)
                    with dashboard.get_conn() as preserved:
                        self.assertEqual(preserved.execute('SELECT data FROM behavior_applications').fetchone()[0],'PRIVATE LEGACY RECORD')
        finally:
            c=psycopg2.connect(dsn);c.autocommit=True
            c.cursor().execute('DROP SCHEMA '+schema+' CASCADE');c.close()


if __name__=='__main__':unittest.main()
