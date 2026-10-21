"""Cycle review report operations against disposable PostgreSQL and a fake model."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import db
from behavior_report.api import register
from copilot.ai_api import register as register_errors
from legacy_schema import migrate
from test_legacy_cloud_schema import PostgreSQLFixture

CONFIG = {'api_base_url': 'https://model.example/v1', 'api_key': 'TEST_ONLY_REPORT_KEY', 'model_name': 'test-model'}


class CycleReviewAPITests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        migrate()
        self.app = FastAPI()
        register_errors(self.app)
        self.store = register(self.app, Path(self.temp.name), Path(self.temp.name))
        self.store.initialize()
        self.original = self.store.create_report('2026-10-20', 30, '原有报告', '{}')

    def test_generate_view_and_delete_keep_original_reports(self):
        async def model(messages, cfg):
            self.assertEqual(cfg['key'], CONFIG['api_key'])
            self.assertIn('数据摘要', messages[0]['content'])
            yield {'text': '## 阶段变化\n新的周期复盘'}
            yield {'done': True}

        with TestClient(self.app) as client, patch('copilot.transport.qwen_stream', model):
            headers = {'X-Copilot-Request': '1'}
            r = client.post('/api/behavior-report/generate?period_days=30', json={'ai_config': CONFIG}, headers=headers)
            self.assertEqual(r.status_code, 201, r.text)
            created = r.json()
            self.assertIn('新的周期复盘', created['content'])
            self.assertNotIn(CONFIG['api_key'], str(created))
            self.assertEqual(len(client.get('/api/behavior-report').json()), 2)
            self.assertEqual(client.get('/api/behavior-report/' + str(created['id'])).json()['content'], created['content'])
            self.assertEqual(client.delete('/api/behavior-report/' + str(created['id']), headers=headers).status_code, 204)
            self.assertEqual(client.get('/api/behavior-report').json(), [self.original])

    def test_missing_configuration_and_invalid_period_create_nothing(self):
        with TestClient(self.app) as client:
            for body, days, expected in (({}, 30, 422), ({'ai_config': CONFIG}, 6, 400)):
                r = client.post('/api/behavior-report/generate?period_days=' + str(days), json=body, headers={'X-Copilot-Request': '1'})
                self.assertEqual(r.status_code, expected, r.text)
            self.assertEqual(client.get('/api/behavior-report').json(), [self.original])

    def test_model_failure_is_not_saved_as_a_successful_report(self):
        async def failed(messages, cfg):
            yield {'text': 'partial result'}
            raise RuntimeError('TEST_ONLY_PRIVATE_PROVIDER_ERROR')

        with TestClient(self.app) as client, patch('copilot.transport.qwen_stream', failed):
            r = client.post('/api/behavior-report/generate', json={'ai_config': CONFIG}, headers={'X-Copilot-Request': '1'})
            self.assertEqual(r.status_code, 502, r.text)
            self.assertNotIn('TEST_ONLY_PRIVATE_PROVIDER_ERROR', r.text)
            self.assertEqual(client.get('/api/behavior-report').json(), [self.original])
