"""Original HTTP contracts across database records and GitHub publications."""
import json
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from copilot.api import register as register_course
from reading.api import register as register_reading
from migration_api import register as register_migrations
from test_legacy_cloud_content import CloudFixture, OWN, DATE

COURSE=('# 第003课：确认偏误\n日期：2026-10-17\n## 引导问题\n问题\n## 核心概念\n概念\n## 完整示范\n假设案例\n'
        '## 误区与边界\n边界\n## 练习\n问题\n\n---\n\n## 参考分析\n分析\n## 自查\n自查\n## 记忆提示\n提示\n[来源](https://example.org/source)')


class CloudHTTPFixture(CloudFixture):
    def setUp(self):
        super().setUp();self.aid=self.source_article();self.migrate_files()
        self.app=FastAPI()
        with patch('copilot.api.make_store',return_value=self.course),patch('reading.api.make_store',return_value=self.reader):
            register_course(self.app,self.root,self.tmp.name)
            _,self.service=register_reading(self.app,self.root,self.tmp.name)
        register_migrations(self.app,self.course,self.root)
        async def model(messages,cfg):
            self.assertEqual(cfg['key'],OWN['api_key'])
            if 'COPILOT_SOURCES' in messages[0]['content']:
                yield {'text':COURSE+'\n<!-- COPILOT_SOURCES -->\n摘要 [来源](https://example.org/source)'}
            else:yield {'text':'## 核心观点\nPublic generated reading guide.\n## 边界\n仅依据文章。'}
            yield {'done':True}
        self.model=patch('copilot.transport.qwen_stream',model);self.model.start();self.addCleanup(self.model.stop)


class LegacyCloudAPITests(CloudHTTPFixture):
    def test_course_generation_publication_learning_and_reading_ai(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            h={'X-Copilot-Request':'1'}
            self.assertEqual(client.get('/api/copilot/today-task').status_code,200)
            for existing in self.course.scan()['lessons']:
                self.course.learning(existing['lesson_no'],'completed',existing['version'],'http-complete-'+str(existing['lesson_no']))
            r=client.post('/api/copilot/generations',json={'lesson_no':3,'key':'http-generate','ai_config':OWN},headers=h)
            self.assertEqual(r.status_code,200,r.text);self.assertIn('event: completed',r.text)
            draft=client.get('/api/copilot/drafts').json()['items'][0]
            r=client.post('/api/copilot/publications',json={'draft_id':draft['id'],'version':draft['version'],'key':'http-publish'},headers=h)
            self.assertEqual(r.status_code,200,r.text)
            lesson=client.get('/api/copilot/lessons/3').json()
            self.assertIn('github_url',lesson)
            r=client.post('/api/copilot/lessons/3/summary',json={'summary':'PRIVATE HTTP SUMMARY','time_spent_seconds':20,'version':lesson['version'],'key':'http-summary'},headers=h)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(client.get('/api/copilot/lessons/3/learning-record').json()['summary_text'],'PRIVATE HTTP SUMMARY')
            r=client.post('/api/reading/articles/'+self.aid+'/guide',json={'data':{'key':'http-guide','ai_config':OWN}},headers=h)
            self.assertEqual(r.status_code,200,r.text);key=r.json()['id']
            for _ in range(100):
                job=client.get('/api/reading/jobs/'+key).json()
                if job['state'] not in ('queued','running'):break
                time.sleep(.01)
            self.assertEqual(job['state'],'ready',job)
            self.assertIn('Public generated',client.get('/api/reading/articles/'+self.aid).json()['guide'])
            self.assertNotIn(OWN['api_key'],json.dumps(job))
            self.assertNotIn('PRIVATE HTTP SUMMARY',json.dumps(self.repository.commits[self.repository.head]['files']))
    def test_migration_status_and_owner_only_boundaries(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            r=client.get('/api/migrations');self.assertEqual(r.status_code,200,r.text)
            self.assertNotIn('PRIVATE ORIGINAL NOTE',r.text)
            self.assertEqual(client.post('/api/migrations/files/preview').status_code,403)
            try:from tenancy import current_user
            except ImportError:
                from contextvars import ContextVar
                from types import ModuleType
                import sys
                tenancy=ModuleType('tenancy');tenancy.current_user=ContextVar('migration_test_identity',default=None)
                mock=patch.dict(sys.modules,{'tenancy':tenancy});mock.start();self.addCleanup(mock.stop)
                current_user=tenancy.current_user
            token=current_user.set({'id':'someone','schema_name':'fake','is_owner':False})
            try:self.assertEqual(client.get('/api/migrations').status_code,403)
            finally:current_user.reset(token)
