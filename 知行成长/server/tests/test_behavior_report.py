"""Behavior reports use request AI credentials and only save completed responses."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from behavior_report.api import register
from copilot.ai_api import register as register_ai
from test_legacy_cloud_schema import PostgreSQLFixture

AI = {'api_base_url': 'https://provider.example/v1', 'api_key': 'PRIVATE_TEST_KEY', 'model_name': 'test-report'}
SUMMARY = {'period': '近30天', 'checkins': {'total_days': 3}, 'habits': {'total_minutes': 20}}


class BehaviorReportTests(PostgreSQLFixture):
    def setUp(self):
        self.raw_connect = db.connect
        super().setUp()
        app = FastAPI()
        register_ai(app)
        self.store = register(app, Path('/unused'), Path('/unused/runtime'))
        self.store.initialize()
        self.client = TestClient(app, base_url='http://localhost')
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.headers = {'X-Copilot-Request': '1'}
        summary = patch('behavior_report.analyzer.collect_data_summary', return_value=SUMMARY)
        summary.start(); self.addCleanup(summary.stop)
        self.calls = []

        async def model(messages, config):
            self.calls.append((messages, config))
            yield {'text': '## 行为模式\n已坚持三天，建议继续保持。'}
            yield {'done': True}

        stream = patch('copilot.transport.qwen_stream', model)
        stream.start(); self.addCleanup(stream.stop)

    def generate(self, **updates):
        return self.client.post('/api/behavior-report/generate?period_days=30',
                                json={'ai_config': AI} | updates, headers=self.headers)

    def test_missing_configuration_and_cross_origin_writes_do_not_generate_or_save(self):
        self.assertEqual(self.generate(ai_config=None).status_code, 422)
        self.assertEqual(self.client.post('/api/behavior-report/generate', json={'ai_config': AI}).status_code, 403)
        for extra in ({'Origin': 'https://foreign.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            response = self.client.post('/api/behavior-report/generate', json={'ai_config': AI}, headers=self.headers | extra)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get('/api/behavior-report').json(), [])
        self.assertEqual(self.calls, [])

    def test_completed_model_output_is_saved_using_current_browser_config_and_old_reports_remain_readable(self):
        old = self.store.create_report('2026-01-01', 7, '原有报告')
        response = self.generate()
        self.assertEqual(response.status_code, 201, response.text)
        report = response.json()
        self.assertIn('已坚持三天', report['content'])
        self.assertEqual(json.loads(report['data_summary']), SUMMARY)
        self.assertEqual(self.calls[0][1], {'url': 'https://provider.example/v1/chat/completions', 'key': AI['api_key'], 'model': AI['model_name'], 'price_version': '', 'input_price': '', 'output_price': ''})
        self.assertNotIn(AI['api_key'], json.dumps(self.client.get('/api/behavior-report').json()))
        self.assertEqual(self.client.get('/api/behavior-report/' + str(old['id'])).json()['content'], '原有报告')
        self.assertEqual(self.client.delete('/api/behavior-report/' + str(old['id']), headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/api/behavior-report/' + str(old['id'])).status_code, 404)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_model_failure_empty_and_incomplete_output_never_become_successful_reports(self):
        async def failure(messages, config):
            raise RuntimeError('provider secret ' + AI['api_key'])
            yield
        async def empty(messages, config):
            yield {'done': True}
        async def incomplete(messages, config):
            yield {'text': '未完成的响应'}
        for model in (failure, empty, incomplete):
            with patch('copilot.transport.qwen_stream', model):
                response = self.generate()
            self.assertEqual(response.status_code, 502, response.text)
            self.assertNotIn(AI['api_key'], response.text)
            self.assertEqual(self.client.get('/api/behavior-report').json(), [])
        self.assertEqual(self.generate().status_code, 201, 'an explicit retry can save a real report')
        self.assertEqual(len(self.client.get('/api/behavior-report').json()), 1)

    def test_disconnect_cancels_inflight_model_without_saving(self):
        cancelled = []
        started = []
        async def slow(messages, config):
            try:
                started.append(True)
                await asyncio.sleep(10)
                yield {'text': '不应保存'}
                yield {'done': True}
            finally:
                cancelled.append(True)
        async def disconnected(request):
            return bool(started)
        with patch('copilot.transport.qwen_stream', slow), patch('starlette.requests.Request.is_disconnected', disconnected):
            response = self.generate()
        self.assertEqual(response.status_code, 499, response.text)
        self.assertEqual(self.client.get('/api/behavior-report').json(), [])
        self.assertEqual(cancelled, [True], 'disconnect closes the in-flight provider stream')

    def test_other_account_schema_cannot_read_or_delete_a_saved_report(self):
        import psycopg2, uuid
        report = self.generate().json()
        other = 'behavior_other_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as conn:
            conn.cursor().execute('CREATE SCHEMA ' + other)
        try:
            with patch('db.connect', lambda *a, **kw: self.raw_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                self.store.initialize()
                self.assertEqual(self.client.get('/api/behavior-report').json(), [])
                self.assertEqual(self.client.get('/api/behavior-report/' + str(report['id'])).status_code, 404)
                self.assertEqual(self.client.delete('/api/behavior-report/' + str(report['id']), headers=self.headers).status_code, 404)
                self.assertEqual(self.generate().status_code, 201)
        finally:
            with psycopg2.connect(self.dsn) as conn:
                conn.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')
        self.assertEqual(len(self.client.get('/api/behavior-report').json()), 1)


class BehaviorReportSummaryTests(PostgreSQLFixture):
    def test_ai_summary_includes_automatic_learning_and_keeps_durations_separate(self):
        from datetime import date
        import app
        from behavior.store import TABLE_SQL as BEHAVIOR
        from errors.store import TABLE_SQL as ERRORS
        from study_materials import initialize
        from behavior_report.analyzer import collect_data_summary
        with db.connect() as conn:
            conn.executescript(app.SCHEMA)
            conn.executescript(BEHAVIOR)
            conn.executescript(ERRORS)
        initialize()
        with db.connect() as conn:
            conn.execute('''INSERT INTO study_learning_records VALUES
                ('biaoda','lesson.md',1,'练习','收获',120,'2026-10-20T16:30:00Z',
                '2026-10-20T16:30:00Z',1,'summary-key','summary-hash')''')
            conn.execute("INSERT INTO habits VALUES ('2026-10-21',10,'手工补记')")
        with patch('growth_statistics.shanghai_today', return_value=date(2026, 10, 21)):
            summary = collect_data_summary(Path('/unused'), 7)
        self.assertIn('2026-10-15 ~ 2026-10-21', summary['period'])
        self.assertEqual(summary['checkins']['total_days'], 1)
        self.assertEqual(summary['checkins']['module_stats'], {'biaoda': 1})
        self.assertEqual(summary['habits']['total_minutes'], 10)
        self.assertEqual(summary['habits']['source'], 'manual_habits')
        self.assertEqual(summary['duration_sources']['course_learning_seconds'], 120)
        self.assertIn('不相加', summary['duration_sources']['note'])
