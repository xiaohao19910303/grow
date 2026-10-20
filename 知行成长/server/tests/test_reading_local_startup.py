"""Local article files still use PostgreSQL metadata after a service restart."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from reading.api import register
from reading.store import ReadingStore
from test_legacy_cloud_schema import PostgreSQLFixture


class LocalReadingStartupTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'materials'
        self.root.mkdir()
        self.runtime = Path(temporary.name) / 'runtime'
        self.store = ReadingStore(self.root, self.runtime)
        backend = patch.dict('os.environ', {'PLAN_CONTENT_BACKEND': 'local'})
        backend.start()
        self.addCleanup(backend.stop)

    def test_initialize_postgresql_without_sqlite_snapshot_and_preserve_saved_articles(self):
        with patch('plans.backup.database_snapshot', side_effect=AssertionError('No SQLite backup of PostgreSQL')):
            self.store.initialize()
        article = self.store.import_from_paste('历史文章', '这是已保存的正文。' * 30)
        self.store.initialize()
        self.assertEqual(self.store.library()['total'], 1)
        self.assertEqual(self.store.article(article['id'])['full_content'], '这是已保存的正文。' * 30)

    def test_real_article_route_reads_saved_body_after_initialize(self):
        self.store.initialize()
        article = self.store.import_from_paste('可恢复的历史文章', '本次验证使用本地保存的正文。' * 30)
        app = FastAPI()
        with patch('reading.api.make_store', return_value=self.store):
            register(app, self.root, self.runtime)
        with TestClient(app) as client:
            history = client.get('/api/reading/library')
            self.assertEqual(history.status_code, 200, history.text)
            detail = client.get('/api/reading/articles/' + article['id'])
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()['full_text'], '# 可恢复的历史文章\n\n' + '本次验证使用本地保存的正文。' * 30)
