"""Browser-owned AI credentials: reject fallback and never persist request secrets."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.ai_config import config, require_config, remove_server_config
from copilot.api import register as register_copilot
from copilot.core import Problem
from plans.api import register as register_plans
from plans.generation import PlanGenerator
from plans.github import GitHubContent
from test_github_plans import B, D
from cloud_fixtures import AsyncCloudFixture
from test_legacy_cloud_schema import PostgreSQLFixture

OWN = {'api_base_url': 'https://user-model.example/v1', 'api_key': 'USER_SECRET_TEST_ONLY', 'model_name': 'user-model'}


class BrowserConfigTests(unittest.TestCase):
    def test_no_environment_or_database_fallback(self):
        with patch.dict(os.environ, {'QWEN_API_KEY': 'SERVER_SECRET', 'QWEN_MODEL': 'server-model', 'QWEN_BASE_URL': 'https://server.example'}):
            self.assertEqual(config()['key'], '')
            self.assertEqual(config(object())['model'], '')
            for value in (None, {}, {**OWN, 'api_key': ''}, {**OWN, 'model_name': ''}):
                with self.assertRaises(Problem): require_config(value)
            self.assertEqual(require_config(OWN)['url'], OWN['api_base_url']+'/chat/completions')
            full = {**OWN, 'api_base_url': OWN['api_base_url']+'/chat/completions'}
            self.assertEqual(require_config(full), require_config(OWN))
            for url in ('http://model.example/v1', 'https://user:pass@example.com', 'https://example.com/?key=secret'):
                with self.assertRaises(Problem): require_config({**OWN, 'api_base_url': url})

    def test_removes_obsolete_credentials_without_other_settings(self):
        import sqlite3
        for identity, column in (('key','value'), ('id','data')):
            with sqlite3.connect(':memory:') as c:
                c.execute(f'CREATE TABLE copilot_settings ({identity} TEXT PRIMARY KEY,{column} TEXT)')
                c.executemany('INSERT INTO copilot_settings VALUES (?,?)', [('api_key','OLD_SECRET'), ('api_base_url','OLD_URL'), ('model_name','OLD_MODEL'), ('generation_total_timeout_seconds','300')])
                remove_server_config(c)
                self.assertEqual(c.execute('SELECT * FROM copilot_settings').fetchall(), [('generation_total_timeout_seconds','300')])

    def test_http_settings_do_not_read_write_or_echo_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = FastAPI()
            store = register_copilot(app, tmp, Path(tmp)/'runtime')
            # Even a broken legacy module must allow testing the user's own config.
            store.startup_error = Problem('migration', 'not ready', 503)
            with patch.object(store, 'get_setting', side_effect=AssertionError('No remote config reads')), \
                 patch.object(store, 'update_settings', side_effect=AssertionError('No remote config writes')), \
                 TestClient(app, base_url='http://localhost') as client:
                self.assertEqual(client.get('/api/copilot/settings').json(), {'storage':'browser','requires_own_config':True})
                headers = {'X-Copilot-Request':'1'}
                r = client.put('/api/copilot/settings', json=OWN, headers=headers)
                self.assertEqual(r.status_code, 410)
                r = client.post('/api/copilot/settings/test', json={**OWN, 'model_name': []}, headers=headers)
                self.assertEqual(r.status_code, 422)
                self.assertNotIn(OWN['api_key'], r.text)
                async def broken(messages, cfg):
                    raise RuntimeError(cfg['key'])
                    yield
                with patch('copilot.transport.qwen_stream', broken):
                    r = client.post('/api/copilot/settings/test', json=OWN, headers=headers)
                self.assertEqual(r.status_code, 200)
                self.assertFalse(r.json()['ok'])
                self.assertNotIn(OWN['api_key'], r.text)


class GenerationRouteCredentials(PostgreSQLFixture):
    def test_all_generation_routes_require_browser_config(self):
        from reflections.api import register as register_reflections
        from reading.api import register as register_reading
        with tempfile.TemporaryDirectory() as tmp:
            app = FastAPI()
            register_copilot(app, tmp, Path(tmp)/'runtime')
            reflection_store, _ = register_reflections(app, tmp, Path(tmp)/'runtime')
            reflection_store.initialize()
            register_reading(app, tmp, Path(tmp)/'runtime')
            with patch('plans.api.make_store', return_value=type('Store', (), {'startup_error':None, 'remote':True})()):
                register_plans(app, tmp, Path(tmp)/'runtime')
            routes = [('/api/copilot/generations', {'lesson_no':3,'key':'test-key-123'}),
                      ('/api/plans/generate', {'data':{'kind':'plan','key':'test-key','brief':B}}),
                      ('/api/plans/drafts/draft/refine', {'data':{'key':'test-key'}}),
                      ('/api/reflections/ref-test/assist', {'kind':'organize','snapshot':{'text':'hello'},'key':'test-key-123'})]
            routes += [('/api/reading/articles/article-test/'+kind, {'data':{'key':'test-key'}}) for kind in ('guide','summary','english')]
            with TestClient(app, base_url='http://localhost') as client, patch.dict(os.environ, {'QWEN_API_KEY':'SERVER_SECRET'}):
                for path, body in routes:
                    r = client.post(path, json=body, headers={'X-Copilot-Request':'1'})
                    self.assertEqual(r.status_code, 422, (path,r.text))
                    self.assertIn('自己的', r.json()['message'])


class GenerationCredentials(AsyncCloudFixture):
    async def test_model_receives_only_request_config_and_journal_has_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.s
            calls = []
            async def model(messages, cfg):
                calls.append(dict(cfg))
                yield {'text': json.dumps(D)}
                yield {'done':True}
            generator = PlanGenerator(store, model)
            body = {'key':'browser-generate', 'kind':'plan', 'brief':B, 'ai_config':OWN}
            with patch.dict(os.environ, {'QWEN_API_KEY':'SERVER_SECRET'}):
                attempt = generator.begin(body)
                await asyncio.gather(*list(generator.tasks.values()))
            self.assertEqual(calls[0]['key'], OWN['api_key'])
            self.assertEqual(calls[0]['model'], OWN['model_name'])
            saved = store.get('learning_ai_attempts', attempt['id'])
            self.assertEqual(saved['state'], 'ready', saved)
            serialized = json.dumps(store.rows('learning_ai_attempts')+store.rows('learning_drafts'))
            for secret in (OWN['api_key'], OWN['api_base_url'], 'SERVER_SECRET', 'ai_config'):
                self.assertNotIn(secret, serialized)
            # An idempotent replay does not invoke the model or depend on a saved key.
            generator.begin(body)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
