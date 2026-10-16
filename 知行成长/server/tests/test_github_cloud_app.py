"""Boot the real application with isolated PostgreSQL and an HTTP GitHub simulator."""
import importlib
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
                patch('plans.api.make_store', side_effect=lambda root, runtime: GitHubPlans(root,runtime,
                    GitHubContent('owner/courses','main','TEST_ONLY_TOKEN',transport=httpx.MockTransport(repository)))):
                dashboard = importlib.import_module('app')
                dashboard.PENDING_SYNC_FILE = dashboard.DB_PATH/'no-pending-sync.json'
                with TestClient(dashboard.app, base_url='https://cloud.example', client=('198.51.100.1',1234)) as client:
                    health=client.get('/api/health')
                    self.assertEqual(health.status_code,200)
                    self.assertEqual(health.json(),{'ok':True,'revision':'test-deploy-revision',
                                                   'plan_storage':'github','learning_plans_ready':True})
                    self.assertEqual(client.get('/').status_code,401)
                    client.auth=('owner',os.environ['APP_PASSWORD'])
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
        finally:
            c=psycopg2.connect(dsn);c.autocommit=True
            c.cursor().execute('DROP SCHEMA '+schema+' CASCADE');c.close()


if __name__=='__main__':unittest.main()
