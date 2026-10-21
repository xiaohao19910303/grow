"""Report facts share the learning calendar's durable completion projection."""
import json
from pathlib import Path
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import db
from test_legacy_cloud_schema import PostgreSQLFixture


class GrowthStatisticsTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        import app
        from copilot.schema import TABLES
        from study_materials import initialize
        from action_plans import SCHEMA
        with db.connect() as c:
            c.executescript(app.SCHEMA)
            c.executescript(TABLES)
            c.executescript(SCHEMA)
            for module in app.DEFAULT_MODULES:
                c.execute('INSERT INTO modules VALUES (?,?,?,?)',
                          (module['id'], module['name'], module['color'], module['order']))
        initialize()

    def course(self, stamp='2026-10-20T16:30:00Z', seconds=120):
        with db.connect() as c:
            c.execute('''INSERT INTO study_learning_records VALUES
                ('biaoda','lesson.md',1,'练习','收获',?,?,?,1,'growth-key','growth-hash')''',
                      (seconds, stamp, stamp))

    def test_week_report_counts_automatic_learning_without_manual_checkin(self):
        import app
        self.course()
        # Local date is Oct 21 even when the durable timestamp is Oct 20 UTC.
        with patch('growth_statistics.shanghai_today', return_value=date(2026, 10, 21)):
            result = app.build_report(7)
        self.assertEqual(result['active_days'], 1)
        self.assertEqual(next(m for m in result['modules'] if m['name'] == '结构化表达')['days'], 1)
        self.assertEqual(result['streak'], 1)

    def test_manual_and_automatic_same_module_day_are_counted_once_and_retraction_updates_reports(self):
        from growth_statistics import collect_activity
        self.course()
        with db.connect() as c:
            c.execute("INSERT INTO checkins VALUES ('2026-10-21','biaoda',2),('2026-10-20','yingyu',0)")
            c.execute("INSERT INTO habits VALUES ('2026-10-20',0,'坚持记录')")
            facts = collect_activity(c, '2026-10-15', '2026-10-21', today=date(2026, 10, 21))
            self.assertEqual(facts['module_stats'], {'biaoda': 1})
            self.assertEqual(facts['active_days'], 2)
            self.assertEqual(facts['streak'], 2)
            c.execute('DELETE FROM study_learning_records')
            c.execute('DELETE FROM checkins')
            facts = collect_activity(c, '2026-10-15', '2026-10-21', today=date(2026, 10, 21))
            self.assertEqual(facts['module_stats'], {})
            self.assertEqual(facts['streak'], 1)

    def test_duration_sources_are_separate_and_running_actions_do_not_invent_time(self):
        from growth_statistics import collect_activity
        self.course(seconds=90)
        with db.connect() as c:
            c.execute("INSERT INTO habits VALUES ('2026-10-21',10,'手工补记')")
            c.execute("INSERT INTO action_plans VALUES ('plan','{}',1)")
            for key, state, minutes in [('done','completed',10),('running','running',99),('auto','completed',0)]:
                c.execute('INSERT INTO action_executions VALUES (?,?,?,?)',
                          (key, 'plan', state, json.dumps({'business_date': '2026-10-21', 'actual_minutes': minutes})))
            facts = collect_activity(c, '2026-10-21', '2026-10-21', today=date(2026, 10, 21))
        self.assertEqual(facts['total_minutes'], 10)
        self.assertEqual(facts['duration_sources']['manual_habit_minutes'], 10)
        self.assertEqual(facts['duration_sources']['course_learning_seconds'], 90)
        self.assertEqual(facts['duration_sources']['action_confirmed_minutes'], 10)
        self.assertIn('不相加', facts['duration_sources']['note'])

    def test_uninitialized_optional_tables_and_incomplete_feedback_do_not_create_learning(self):
        from growth_statistics import collect_activity
        with db.connect() as c:
            c.executescript('''CREATE TABLE learning_plans(id TEXT PRIMARY KEY,data TEXT);
                CREATE TABLE learning_feedback(plan_id TEXT,lesson_no INTEGER,data TEXT);''')
            c.execute('INSERT INTO learning_plans VALUES (?,?)', ('custom', json.dumps({'name': '专属训练'})))
            c.execute('INSERT INTO learning_feedback VALUES (?,1,?)', ('custom', json.dumps({'state': 'unknown', 'date': '2026-10-21'})))
            self.assertEqual(collect_activity(c, today=date(2026, 10, 21))['active_days'], 0)
            c.execute('UPDATE learning_feedback SET data=?', (json.dumps({'state': 'completed', 'date': '2026-10-21'}),))
            facts = collect_activity(c, today=date(2026, 10, 21))
            self.assertEqual(facts['module_stats'], {'custom': 1})
            self.assertEqual(facts['modules'][0]['name'], '专属训练')
            c.executescript('DROP TABLE study_learning_records; DROP TABLE copilot_learning_records; DROP TABLE learning_feedback; DROP TABLE learning_plans; DROP TABLE action_executions;')
            self.assertEqual(collect_activity(c, today=date(2026, 10, 21))['duration_sources']['course_learning_seconds'], 0)

    def test_real_draft_completion_replay_history_and_week_month_reports_share_facts(self):
        import app as main_app
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from learning_checkins import read_checkins
        from study_materials import register
        from study_notes import register as register_notes
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            course = root / '结构化表达/每日练习/Day 001.md'
            course.parent.mkdir(parents=True)
            course.write_text('# 练习\n\n合成测试课程')
            app = FastAPI()
            register(app, root)
            register_notes(app)
            app.get('/api/report')(main_app.get_report)
            client = TestClient(app)
            path = '/api/study-materials/biaoda/Day%20001.md'
            lesson = client.get(path).json()['lesson']
            headers = {'X-Copilot-Request': '1'}
            with patch('growth_statistics.shanghai_today', return_value=date(2026, 10, 1)):
                draft = client.put('/api/study-notes/biaoda/Day%20001.md', json={
                    'notes': '还在练习', 'answers': {}, 'version': lesson['version'],
                    'revision': 0, 'key': 'growth-note-first'}, headers=headers)
                self.assertEqual(draft.status_code, 200, draft.text)
                self.assertEqual(client.get('/api/report').json()['active_days'], 0)
                body = dict(summary_text='完成练习', time_spent_seconds=125,
                            version=lesson['version'], revision=0, key='growth-complete-first')
                with patch('study_materials.datetime') as stamp:
                    stamp.now.return_value = datetime(2026, 10, 1, 0, 15, tzinfo=ZoneInfo('Asia/Shanghai'))
                    first = client.post(path + '/learning-record', json=body, headers=headers)
                    replay = client.post(path + '/learning-record', json=body, headers=headers)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(first.json(), replay.json())
                with db.connect() as c:
                    self.assertEqual(read_checkins(c)['checkins'], {'2026-10-01': {'biaoda': 3}})
                history = client.get('/api/study-materials/learning-history?start=2026-10-01&end=2026-10-01').json()
                self.assertEqual(history['total'], 1)
                self.assertEqual(history['items'][0]['completed_at'], first.json()['completed_at'])
                for window, start in [('week', '2026-09-25'), ('month', '2026-09-02')]:
                    response = client.get('/api/report', params={'range': window})
                    self.assertEqual(response.status_code, 200, response.text)
                    report = response.json()
                    self.assertEqual((report['start'], report['end']), (start, '2026-10-01'))
                    self.assertEqual((report['active_days'], report['streak']), (1, 1))
                    self.assertEqual(report['duration_sources']['course_learning_seconds'], 125)
                    self.assertEqual(report['total_minutes'], 0)
                    self.assertEqual(next(m for m in report['modules'] if m['name'] == '结构化表达')['days'], 1)

    def test_period_filter_does_not_truncate_streak_or_include_future_activity(self):
        from growth_statistics import collect_activity
        with db.connect() as c:
            c.execute("INSERT INTO checkins VALUES ('2026-10-19','renzhi',3),('2026-10-20','renzhi',3),('2026-10-22','renzhi',3)")
            facts = collect_activity(c, '2026-10-20', '2026-10-21', today=date(2026, 10, 21))
        self.assertEqual(facts['total_days'], 1)
        self.assertEqual(facts['module_stats'], {'renzhi': 1})
        self.assertEqual(facts['streak'], 2)

    def test_week_and_ai_report_include_new_free_and_guided_reflections_with_legacy_reviews(self):
        import app
        from behavior_report.analyzer import collect_data_summary
        from behavior.store import TABLE_SQL as BEHAVIOR
        from errors.store import TABLE_SQL as ERRORS
        from reflections.store import ReflectionsStore
        import os
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'PLAN_CONTENT_BACKEND': 'github'}):
            store = ReflectionsStore(Path(temporary), Path(temporary) / 'runtime')
            store.initialize()
            for number, (day, guided) in enumerate([
                ('2026-10-15', {}),
                ('2026-10-21', {'expected': '先完成练习', 'observed': '完成一课', 'causes': '拆小步骤', 'adjustment': '明日继续'}),
                ('2026-10-14', {}),
                ('2026-10-22', {}),
                ('2026-10-18', {})]):
                saved = store.create({'record_date': day, 'raw_text': '真实日常记录',
                                      'prompt_kind': '自由记录', 'guided_answers': guided}, f'growth-reflection-{number}')
                if number == 4:
                    store.archive(saved['id'], 'archive-growth-reflection')
            with db.connect() as c:
                c.executescript(BEHAVIOR + ERRORS)
                c.execute("INSERT INTO reviews(date,thought) VALUES ('2026-10-20','保留旧四问'),('2026-10-14','范围外旧四问')")
                c.execute("INSERT INTO habits VALUES ('2026-10-21',10,'手工补记')")
            with patch('growth_statistics.shanghai_today', return_value=date(2026, 10, 21)):
                weekly = app.build_report(7)
                summary = collect_data_summary(Path('/unused'), 7)
            self.assertEqual(weekly['reviews'], 3)
            self.assertEqual(summary['reviews']['total'], 3)
            self.assertEqual(weekly['total_minutes'], 10)
            self.assertEqual(summary['habits']['total_minutes'], 10)
            self.assertEqual(weekly['duration_sources'], summary['duration_sources'])

    def test_reflection_count_handles_optional_tables_and_inclusive_boundaries(self):
        from growth_statistics import count_reflections
        with db.connect() as c:
            self.assertEqual(count_reflections(c, '2026-10-15', '2026-10-21'), 0)
            c.execute("INSERT INTO reviews(date,thought) VALUES ('2026-10-15','开始边界'),('2026-10-21','结束边界')")
            self.assertEqual(count_reflections(c, '2026-10-15', '2026-10-21'), 2)
            c.execute('DROP TABLE reviews')
            c.execute('CREATE TABLE reflection_entries(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            for key, day, archive in [('start', '2026-10-15', None), ('end', '2026-10-21', None), ('old', '2026-10-14', None), ('hidden', '2026-10-20', '2026-10-21T10:00:00+08:00')]:
                c.execute('INSERT INTO reflection_entries VALUES (?,?)', (key, json.dumps({'record_date': day, 'archived_at': archive})))
            self.assertEqual(count_reflections(c, '2026-10-15', '2026-10-21'), 2)
