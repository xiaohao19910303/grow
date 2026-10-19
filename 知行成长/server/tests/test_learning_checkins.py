"""Automatic check-ins use durable completions, never a second mutable copy."""
import json
from pathlib import Path
import shutil
import tempfile

import db
from test_legacy_cloud_schema import PostgreSQLFixture


class LearningCheckinTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        with db.connect() as c:
            c.executescript('''
                CREATE TABLE copilot_learning_records (module_id TEXT, round_id INTEGER, lesson_no INTEGER, completed_at TEXT);
                CREATE TABLE study_learning_records (module_id TEXT, filename TEXT, completed_at TEXT);
                CREATE TABLE learning_plans (id TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE learning_feedback (plan_id TEXT, lesson_no INTEGER, data TEXT);
            ''')

    def snapshot(self):
        from learning_checkins import read_checkins
        with db.connect() as c:
            return read_checkins(c)

    def test_classifies_completions_deduplicates_and_uses_shanghai_date(self):
        with db.connect() as c:
            c.execute("INSERT INTO copilot_learning_records VALUES ('renzhi',1,1,'2026-10-17T16:30:00Z'),('renzhi',1,2,'2026-10-18T12:00:00+08:00')")
            c.execute("INSERT INTO study_learning_records VALUES ('yingyu','one.md','2026-10-18T10:00:00+08:00'),('biaoda','two.md','2026-10-17T10:00:00+08:00')")
        self.assertEqual(self.snapshot()['checkins'], {
            '2026-10-18': {'renzhi': 3, 'yingyu': 3}, '2026-10-17': {'biaoda': 3}})
        self.assertEqual(self.snapshot(), self.snapshot())

    def test_retracting_completion_removes_only_its_automatic_checkin(self):
        with db.connect() as c:
            c.execute("INSERT INTO copilot_learning_records VALUES ('renzhi',1,1,'2026-10-18T12:00:00+08:00')")
        self.assertEqual(self.snapshot()['checkins']['2026-10-18']['renzhi'], 3)
        with db.connect() as c:
            c.execute('DELETE FROM copilot_learning_records')
        self.assertEqual(self.snapshot()['checkins'], {})

    def test_plans_use_their_own_category_and_pending_feedback_does_not_check_in(self):
        with db.connect() as c:
            c.execute('INSERT INTO learning_plans VALUES (?,?)', ('plan-one', json.dumps({'name': '沟通练习'})))
            for number, state in ((1, 'completed'), (2, 'unknown')):
                c.execute('INSERT INTO learning_feedback VALUES (?,?,?)', ('plan-one', number, json.dumps({'state': state, 'date': '2026-10-18T12:00:00+08:00'})))
        result = self.snapshot()
        self.assertEqual(result['checkins'], {'2026-10-18': {'plan-one': 3}})
        self.assertEqual(result['modules'][0]['name'], '沟通练习')

    def test_empty_or_invalid_dates_and_other_rounds_do_not_invent_checkins(self):
        with db.connect() as c:
            c.execute("INSERT INTO copilot_learning_records VALUES ('renzhi',1,1,''),('renzhi',1,2,'invalid'),('renzhi',2,3,'2026-10-18T12:00:00+08:00')")
        self.assertEqual(self.snapshot()['checkins'], {})

    def test_optional_uninitialized_course_tables_are_empty(self):
        with db.connect() as c:
            c.executescript('DROP TABLE copilot_learning_records; DROP TABLE study_learning_records; DROP TABLE learning_feedback; DROP TABLE learning_plans;')
        self.assertEqual(self.snapshot(), {'checkins': {}, 'modules': []})


class LearningCheckinIntegrationTests(PostgreSQLFixture):
    def test_actual_course_completion_retry_and_retraction_drive_checkins(self):
        from copilot.core import MODULE, Store
        from learning_checkins import read_checkins
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'materials'
            shutil.copytree(Path(__file__).parent / 'fixtures/renzhi', root / MODULE)
            store = Store(root, Path(temporary) / 'runtime')
            store.initialize()
            store.writer_session(True)
            version = store.lesson(1)['version']
            store.quick_complete(1, 120, version, 'auto-checkin-complete')
            store.quick_complete(1, 120, version, 'auto-checkin-complete')
            day = store.get_learning_record(1)['completed_at'][:10]
            with db.connect() as c:
                self.assertEqual(read_checkins(c)['checkins'], {day: {'renzhi': 3}})
            store.learning(1, 'unknown', store.lesson(1)['version'], 'auto-checkin-retract')
            with db.connect() as c:
                self.assertEqual(read_checkins(c)['checkins'], {})
