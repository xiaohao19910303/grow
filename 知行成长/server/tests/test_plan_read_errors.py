"""Missing course files and a wrong backend return useful JSON errors."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from copilot.core import Problem, encoded
from plans.api import register
from plans.store import Plans, TABLES
from test_legacy_cloud_schema import PostgreSQLFixture


class PlanReadErrorsTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Plans(self.root, self.root / 'runtime')
        with self.store.conn() as c:
            c.executescript(TABLES)
            c.execute('INSERT INTO learning_plans VALUES (?,?)', ('plan-20261017-001', encoded({'id': 'plan-20261017-001'})))
            c.execute('INSERT INTO learning_lessons VALUES (?,?,?)', ('plan-20261017-001', 1,
                encoded({'lesson_no': 1, 'path': '每日课程/第001课.md', 'source': '参考资料/第001课.md'})))
        app = FastAPI()
        @app.exception_handler(Problem)
        async def problem(request, error):
            return JSONResponse({'code': error.code, 'message': error.message}, status_code=error.status)
        with patch('plans.api.make_store', return_value=self.store):
            register(app, self.root, self.root / 'runtime')
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_missing_local_course_returns_json_without_exposing_server_paths(self):
        response = self.client.get('/api/plans/plan-20261017-001/lessons/1')
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()['code'], 'not_found')
        self.assertIn('资料文件缺失', response.json()['message'])
        self.assertNotIn(str(self.root), response.text)

    def test_github_course_never_falls_back_to_local_files(self):
        lesson = self.store.lessons('plan-20261017-001')[0]
        lesson.update(storage='github', commit_sha='a' * 40)
        with self.store.conn() as c:
            c.execute('UPDATE learning_lessons SET data=?', (encoded(lesson),))
        with patch.object(self.store, 'read_text', side_effect=AssertionError('Do not read local files')):
            response = self.client.get('/api/plans/plan-20261017-001/lessons/1')
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['code'], 'content_backend')
        self.assertIn('GitHub', response.json()['message'])
