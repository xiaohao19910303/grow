"""Behavior reports use request AI credentials and only save completed responses."""
import asyncio
import json
import unittest
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


class BehaviorReportEvidenceTests(unittest.TestCase):
    def test_single_period_summary_requires_missing_evidence_and_sample_limits(self):
        from behavior_report.analyzer import build_prompt
        data = {**SUMMARY, 'predictions': {'total': 0, 'resolved': 0, 'accuracy': 0},
                'errors': {'total': 0, 'repeat_rate': 0}}
        prompt = build_prompt(data)
        self.assertIn(json.dumps(data, ensure_ascii=False, indent=2), prompt)
        for boundary in ('没有记录不等于没有学习', '不得判断上升、下滑或改善',
                         '不能判断过度自信、保守或校准水平', '不解释为表现差或真实的0%水平',
                         '不是计划或课程完成率', '不能证明应用效果', '待验证解释与建议'):
            self.assertIn(boundary, prompt)


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
            self.calls.append((messages, dict(config)))
            yield {'text': '## 行为模式\n已坚持三天，建议继续保持。'}
            yield {'done': True}

        stream = patch('copilot.transport.qwen_stream', model)
        stream.start(); self.addCleanup(stream.stop)

    def generate(self, **updates):
        return self.client.post('/api/behavior-report/generate?period_days=30',
                                json={'ai_config': AI} | updates, headers=self.headers)

    def test_background_api_202_replay_pagination_and_request_lookup_never_restart_model(self):
        import time
        body={'key':'api-background-request','period_days':30,'ai_config':AI}
        response=self.client.post('/api/behavior-report/jobs',json=body,headers=self.headers)
        self.assertEqual(response.status_code,202,response.text);job=response.json()
        self.assertTrue(job['evidence_snapshot_id'])
        for _ in range(100):
            current=self.client.get('/api/behavior-report/jobs/'+job['id']).json()
            if current['state'] not in ('queued','generating'):break
            time.sleep(.01)
        self.assertEqual(current['state'],'ready')
        replay=self.client.post('/api/behavior-report/jobs',json={**body,'ai_config':None},headers=self.headers)
        self.assertEqual(replay.status_code,202);self.assertEqual(replay.json()['result_id'],current['result_id'])
        lookup=self.client.get('/api/behavior-report/jobs/by-request/'+body['key'])
        self.assertEqual(lookup.status_code,200);self.assertEqual(lookup.json()['id'],job['id'])
        page=self.client.get('/api/behavior-report/jobs?page=1&page_size=1').json()
        self.assertEqual(page['total'],1);self.assertEqual(page['items'][0]['id'],job['id'])
        self.assertEqual(self.client.post('/api/behavior-report/jobs/'+job['id']+'/cancel',json={},headers=self.headers).json()['state'],'ready')
        self.assertEqual(self.client.post('/api/behavior-report/jobs',json={**body,'period_days':7},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/behavior-report/jobs',json={**body,'period_days':'30'},headers=self.headers).status_code,422)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(lookup.headers['cache-control'],'no-store')

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

    def test_legacy_disconnect_after_full_model_output_still_cancels_before_result_save(self):
        from starlette.requests import Request
        async def disconnect_when_finished(request):
            with self.store.conn() as c:
                return any(json.loads(r[0]).get('awaiting_confirmation') for r in c.execute('SELECT data FROM behavior_report_jobs'))
        with patch.object(Request,'is_disconnected',disconnect_when_finished):
            response=self.generate()
        self.assertEqual(response.status_code,499,response.text)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.client.get('/api/behavior-report').json(),[])

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
