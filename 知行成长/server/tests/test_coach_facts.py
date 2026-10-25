"""Factual coach projection uses saved tenant records and no model or writes."""
from datetime import date, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2
import db
from platform_schema import TABLES
from test_legacy_cloud_schema import PostgreSQLFixture


class CoachFactTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        with db.connect() as c:
            c.executescript(TABLES)
        from coach_facts import register
        app = FastAPI(); register(app)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.today = date(2026, 10, 25)
        clock = patch('growth_statistics.shanghai_today', return_value=self.today)
        clock.start(); self.addCleanup(clock.stop)

    def get(self):
        response = self.client.get('/api/coach-facts')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertFalse(response.json()['uses_model'])
        return response.json()['fact']

    def checkins(self, days, counts):
        with db.connect() as c:
            for day, count in zip(days, counts):
                for i in range(count):
                    c.execute('INSERT INTO checkins VALUES (?,?,?)', (str(day), 'module-' + str(i), 1))

    def prediction(self, result='correct', day=None):
        with db.connect() as c:
            c.execute('INSERT INTO predictions(date,statement,probability,result) VALUES (?,?,?,?)',
                      (str(day or self.today), '合成预测', 70, result))

    def study(self, age, stamp=None):
        from study_materials import initialize
        initialize()
        day = self.today - timedelta(days=age)
        with db.connect() as c:
            c.execute('INSERT INTO study_learning_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      ('biaoda', 'Day 001.md', 1, '区分事实与判断', '私有笔记不可返回', 120,
                       stamp or str(day), str(day), 1, 'coach-study-key', 'hash'))

    def test_empty_account_and_uninitialized_optional_tables_have_explicit_empty_fact(self):
        fact = self.get()
        self.assertEqual(fact['kind'], 'empty')
        self.assertIn('没有学习', fact['basis'])
        self.assertEqual(fact['evidence']['active_days'], 0)

    def test_three_complete_positive_days_decline_is_about_records_only(self):
        days = [self.today - timedelta(days=i) for i in [3, 2, 1]]
        self.checkins(days, [3, 2, 1])
        self.checkins([self.today], [5])  # Today's incomplete date is excluded.
        fact = self.get()
        self.assertEqual(fact['kind'], 'record_decrease')
        self.assertEqual(fact['evidence']['counts'], [3, 2, 1])
        self.assertEqual(fact['evidence']['dates'], list(map(str, days)))
        self.assertIn('不代表', fact['basis'])

    def test_missing_or_equal_days_cannot_produce_a_decline_claim(self):
        days = [self.today - timedelta(days=i) for i in [3, 2, 1]]
        self.checkins(days, [3, 2, 0])
        self.assertNotEqual(self.get()['kind'], 'record_decrease')
        with db.connect() as c:
            c.execute('DELETE FROM checkins')
        self.checkins(days, [2, 2, 1])
        self.assertNotEqual(self.get()['kind'], 'record_decrease')

    def test_course_gap_threshold_and_existing_learning_record(self):
        self.study(14)
        fact = self.get()
        self.assertEqual(fact['kind'], 'course_gap')
        self.assertEqual(fact['evidence']['gap_days'], 14)
        self.assertEqual(fact['evidence']['threshold_days'], 14)
        self.assertIn('区分事实与判断', fact['message'])
        self.assertIn('不能', fact['basis'])
        self.assertNotIn('私有笔记', json.dumps(fact, ensure_ascii=False))
        with db.connect() as c:
            c.execute('UPDATE study_learning_records SET completed_at=?', (str(self.today - timedelta(days=13)),))
        self.assertNotEqual(self.get()['kind'], 'course_gap')

    def test_course_gap_uses_local_date_instead_of_timestamp_prefix(self):
        self.study(14, '2026-10-11T16:30:00Z')  # Beijing Oct12, only13 days ago.
        self.assertNotEqual(self.get()['kind'], 'course_gap')

    def test_cognitive_course_updates_and_archive_control_gap_without_returning_notes(self):
        from copilot.schema import TABLES as courses
        with db.connect() as c:
            c.executescript(courses)
            c.execute("INSERT INTO copilot_learning_records(module_id,round_id,lesson_no,completion_type,summary_text,completed_at) VALUES ('renzhi',1,1,'quick','PRIVATE LEARNING NOTE','2026-10-01')")
        self.assertEqual(self.get()['kind'], 'course_gap')
        with db.connect() as c:
            c.execute("UPDATE copilot_learning_records SET completed_at='2026-10-24'")
        self.assertNotEqual(self.get()['kind'], 'course_gap')
        with db.connect() as c:
            c.execute("UPDATE copilot_learning_records SET completed_at='2026-10-01',archived=1")
        self.assertNotEqual(self.get()['kind'], 'course_gap')

    def test_rule_priority_is_stable_and_empty_predictions_do_not_invent_percentages(self):
        self.study(15)
        for _ in range(5):self.prediction()
        self.checkins([self.today-timedelta(days=i) for i in (3,2,1)],[3,2,1])
        self.assertEqual(self.get()['kind'], 'record_decrease')
        with db.connect() as c:c.execute('DELETE FROM checkins')
        self.assertEqual(self.get()['kind'], 'course_gap')
        with db.connect() as c:c.execute('UPDATE study_learning_records SET completed_at=?',(str(self.today),))
        self.assertEqual(self.get()['kind'], 'predictions')

    def test_snapshot_transaction_rejects_an_accidental_write(self):
        from coach_facts import snapshot
        def accidental_write(conn, today):
            conn.execute("INSERT INTO habits VALUES ('2026-10-25',99,'must roll back')")
        with patch('coach_facts.project',side_effect=accidental_write):
            with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):snapshot()
        with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM habits').fetchone()[0],0)

    def test_plan_feedback_requires_completed_active_course_and_latest_confirmation(self):
        with db.connect() as c:
            c.executescript('CREATE TABLE learning_plans(id TEXT PRIMARY KEY,data TEXT); CREATE TABLE learning_lessons(plan_id TEXT,lesson_no INTEGER,data TEXT); CREATE TABLE learning_feedback(plan_id TEXT,lesson_no INTEGER,data TEXT);')
            c.execute('INSERT INTO learning_plans VALUES (?,?)', ('plan-fixture', json.dumps({'name':'测试规划', 'status':'active'})))
            c.execute('INSERT INTO learning_lessons VALUES (?,1,?)', ('plan-fixture', json.dumps({'topic':'第一课'})))
            c.execute('INSERT INTO learning_feedback VALUES (?,1,?)', ('plan-fixture', json.dumps({'state':'unknown', 'date':'2026-10-01'})))
        self.assertNotEqual(self.get()['kind'], 'course_gap')
        with db.connect() as c:
            c.execute('UPDATE learning_feedback SET data=?', (json.dumps({'state':'completed','date':'2026-10-01'}),))
        self.assertEqual(self.get()['kind'], 'course_gap')
        with db.connect() as c:
            c.execute('UPDATE learning_plans SET data=?', (json.dumps({'name':'测试规划','status':'paused'}),))
        self.assertNotEqual(self.get()['kind'], 'course_gap')

    def test_prediction_sample_ignores_pending_invalid_and_outside_current_week(self):
        for _ in range(4): self.prediction()
        self.prediction('pending'); self.prediction('unknown')
        self.prediction(day=self.today + timedelta(days=1))
        self.prediction(day=self.today - timedelta(days=self.today.weekday() + 1))
        self.assertNotEqual(self.get()['kind'], 'predictions')
        self.prediction('incorrect')
        fact = self.get()
        self.assertEqual(fact['kind'], 'predictions')
        self.assertEqual(fact['evidence']['resolved'], 5)
        self.assertEqual(fact['evidence']['correct'], 4)
        self.assertEqual(fact['evidence']['accuracy_percent'], 80)
        self.assertIn('校准', fact['basis'])

    def test_future_malformed_dates_and_zero_levels_do_not_create_activity(self):
        self.checkins([self.today + timedelta(days=1), 'invalid'], [1, 1])
        with db.connect() as c:
            c.execute("INSERT INTO checkins VALUES ('2026-10-25','zero',0)")
            c.execute("INSERT INTO habits VALUES ('2026-10-26',100,'未来记录')")
        self.assertEqual(self.get()['kind'], 'empty')

    def test_streak_and_activity_include_manual_notes_without_summing_minutes(self):
        with db.connect() as c:
            c.execute("INSERT INTO habits VALUES ('2026-10-24',20,'手工补记'),('2026-10-25',0,'只记录一句')")
        fact = self.get()
        self.assertEqual(fact['kind'], 'streak')
        self.assertEqual(fact['evidence']['streak'], 2)
        self.assertNotIn('总时长', fact['message'])

    def test_projection_is_read_only_even_when_records_exist(self):
        self.prediction()
        # PostgreSQL itself enforces read-only, rather than asserting SQL call order.
        from coach_facts import snapshot
        original = db.connect
        def readonly():
            conn = original()
            conn.execute('SET TRANSACTION READ ONLY')
            return conn
        with patch('coach_facts.db.connect', side_effect=readonly):
            result = snapshot()
        self.assertFalse(result['uses_model'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM predictions').fetchone()[0], 1)

    def test_no_ai_configuration_or_model_call_is_needed(self):
        with patch('copilot.transport.qwen_stream', side_effect=AssertionError('No model allowed')):
            self.assertEqual(self.get()['kind'], 'empty')

    def test_database_failure_does_not_return_empty_or_leak_details(self):
        with patch('coach_facts.snapshot', side_effect=psycopg2.OperationalError('PRIVATE DATABASE DATA')):
            response = self.client.get('/api/coach-facts')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertNotIn('PRIVATE DATABASE DATA', response.text)
        self.assertNotIn('fact', response.json())
