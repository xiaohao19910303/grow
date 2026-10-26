"""Private course activity and formal curriculum summaries in isolated PostgreSQL."""
from unittest.mock import patch
import uuid

import db
from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2

from test_legacy_cloud_schema import PostgreSQLFixture
import test_plans
from cloud_fixtures import CloudFixture


class CourseActivityTests(PostgreSQLFixture):
    def setUp(self):
        self.raw_connect = db.connect
        super().setUp()
        from course_activity import install_routes
        from fastapi import APIRouter
        router = APIRouter()
        install_routes(router)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = '/library/activity'
        self.headers = {'X-Copilot-Request': '1'}

    def test_resume_preserves_start_and_does_not_create_completion(self):
        self.assertEqual(self.client.get(self.path).json(), {'items': []})
        with patch('course_activity.now', return_value='2026-10-26T12:00:00+08:00'):
            first = self.client.post(self.path, json={'course_key': 'plan:demo', 'lesson_no': 3}, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        with patch('course_activity.now', return_value='2026-10-27T12:00:00+08:00'):
            second = self.client.post(self.path, json={'course_key': 'plan:demo', 'lesson_no': 4}, headers=self.headers).json()
        self.assertEqual(second['started_at'], first.json()['started_at'])
        self.assertEqual(second['lesson_no'], 4)
        self.assertEqual(second['last_opened_at'], '2026-10-27T12:00:00+08:00')
        self.assertEqual(self.client.get(self.path).json()['items'], [second])
        with db.connect() as c:
            self.assertIsNone(c.execute("SELECT to_regclass('study_learning_records')").fetchone()[0])
            self.assertIsNone(c.execute("SELECT to_regclass('learning_feedback')").fetchone()[0])

    def test_writes_require_same_origin_and_valid_course_identity(self):
        body = {'course_key': 'biaoda', 'lesson_no': 1}
        for headers in ({}, {**self.headers, 'Origin': 'https://other.example'}, {**self.headers, 'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.client.post(self.path, json=body, headers=headers).status_code, 403)
        for body in ({'course_key': '../bad', 'lesson_no': 1}, {'course_key': 'plan:', 'lesson_no': 1},
                     {'course_key': 'renzhi', 'lesson_no': True}, {'course_key': 'renzhi', 'lesson_no': 0}):
            self.assertEqual(self.client.post(self.path, json=body, headers=self.headers).status_code, 422)

    def test_activity_is_private_to_database_tenant(self):
        self.client.post(self.path, json={'course_key': 'renzhi', 'lesson_no': 2}, headers=self.headers)
        other = 'course_activity_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:
            c.cursor().execute('CREATE SCHEMA ' + other)
        try:
            with patch('db.connect', lambda *a, **kw: self.raw_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                self.assertEqual(self.client.get(self.path).json()['items'], [])
                self.client.post(self.path, json={'course_key': 'yingyu', 'lesson_no': 5}, headers=self.headers)
            self.assertEqual(self.client.get(self.path).json()['items'][0]['course_key'], 'renzhi')
        finally:
            with psycopg2.connect(self.dsn) as c:
                c.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')


class CourseSummaryTests(CloudFixture):
    adopt = test_plans.StoreTests.adopt
    course = test_plans.StoreTests.course
    # Reuse the existing real GitHub/PG fixture and publishing helpers.
    def test_listing_includes_unpublished_curriculum_and_completion_dates(self):
        from plans.api import register
        pid = self.adopt()
        self.course(pid)
        self.s.feedback(pid, 1, {'state': 'completed', 'comment': 'PRIVATE'}, 'library-complete')
        app = FastAPI()
        register(app, self.root, self.s.db)
        with TestClient(app) as client:
            response = client.get('/api/plans')
        self.assertEqual(response.status_code, 200, response.text)
        item = next(p for p in response.json()['plans'] if p['id'] == pid)
        self.assertEqual(item['curriculum'], test_plans.D)
        self.assertEqual(len(item['lessons']), 1)
        self.assertTrue(item['lessons'][0]['completed_at'])
        self.assertNotIn('PRIVATE', str(item))
