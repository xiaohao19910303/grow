"""Saved article history is paginated metadata; listing never fetches sources."""
import json
from pathlib import Path
from unittest.mock import patch

import db
from reading.store import ReadingStore
from test_legacy_cloud_schema import PostgreSQLFixture


class ReadingLibraryTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.store = ReadingStore(Path('/unused'), Path('/unused-runtime'))
        with db.connect() as c:
            c.execute('CREATE TABLE reading_records(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            for n in range(25):
                doc = dict(id=f'article-{n:03d}', type='article', title=f'历史文章 {n}',
                           saved_at=f'2026-10-{n+1:02d}', summary='摘要', full_content='正文检索词' + 'x' * 10000,
                           guide='导读', tags=['标签'], bookmarked=n == 2, archived=n == 3,
                           feedback={'takeaway': '个人收获'} if n == 4 else {})
                c.execute('INSERT INTO reading_records VALUES (?,?)', (doc['id'], json.dumps(doc)))
            job = dict(id='job-history', type='job', kind='collect', state='ready', created_at='2026-10-18',
                       candidates=[{'title': '原有搜集结果', 'full_content': 'x' * 20000}], raw='private raw')
            c.execute('INSERT INTO reading_records VALUES (?,?)', (job['id'], json.dumps(job)))

    def test_history_is_paginated_searchable_and_excludes_full_documents(self):
        original = db.connect
        with patch('db.connect', wraps=original) as connections:
            first = self.store.library(page=1, page_size=10)
        self.assertEqual(connections.call_count, 1)
        self.assertEqual(first['total'], 24)
        self.assertEqual(len(first['articles']), 10)
        self.assertEqual(first['articles'][0]['id'], 'article-024')
        self.assertFalse({'full_content', 'guide', 'raw'} & first['articles'][0].keys())
        second = self.store.library(page=2, page_size=10)
        self.assertFalse({a['id'] for a in first['articles']} & {a['id'] for a in second['articles']})
        self.assertEqual(self.store.library(search='正文检索词')['total'], 24)
        self.assertEqual(self.store.library(search='个人收获')['total'], 1)
        self.assertEqual(self.store.library(search='%_')['total'], 0)

    def test_filters_and_empty_later_pages_preserve_totals(self):
        self.assertEqual(self.store.library(filter='bookmark')['total'], 1)
        self.assertEqual(self.store.library(filter='feedback')['total'], 1)
        self.assertEqual(self.store.library(filter='archived')['articles'][0]['id'], 'article-003')
        last = self.store.library(page=100)
        self.assertEqual(last['articles'], [])
        self.assertEqual(last['total'], 24)

    def test_job_history_returns_counts_and_links_without_candidate_bodies(self):
        result = self.store.library(kind='jobs')
        self.assertEqual(result['total'], 1)
        job = result['jobs'][0]
        self.assertEqual(job['id'], 'job-history')
        self.assertEqual(job['candidate_count'], 1)
        self.assertNotIn('candidates', job)
        self.assertNotIn('raw', job)
        with db.connect() as c:
            original = json.loads(c.execute("SELECT data FROM reading_records WHERE id='job-history'").fetchone()[0])
        self.assertEqual(original['candidates'][0]['full_content'], 'x' * 20000)

    def test_legacy_nul_does_not_break_listing_or_modify_source(self):
        with db.connect() as c:
            doc = json.loads(c.execute("SELECT data FROM reading_records WHERE id='article-000'").fetchone()[0])
            doc['full_content'] = 'old PDF\x00content'
            raw = json.dumps(doc)
            c.execute("UPDATE reading_records SET data=? WHERE id='article-000'", (raw,))
        self.assertEqual(self.store.library(search='old PDF')['total'], 1)
        with db.connect() as c:
            self.assertEqual(c.execute("SELECT data FROM reading_records WHERE id='article-000'").fetchone()[0], raw)

    def test_api_history_remains_readable_during_document_storage_failure(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from copilot.core import Problem
        from reading.api import register
        self.store.startup_error = Problem('legacy_content_migration', 'Needs repair', 503)
        app = FastAPI()
        with patch('reading.api.make_store', return_value=self.store):
            register(app, Path('/unused'), Path('/unused-runtime'))
        with TestClient(app) as client:
            response = client.get('/api/reading/library?page_size=5')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()['articles']), 5)
            self.assertIn('no-store', response.headers['cache-control'])
            self.assertEqual(client.get('/api/reading/articles/article-000').status_code, 503)
            self.assertEqual(client.get('/api/reading/library?page=0').status_code, 422)
            self.assertEqual(client.get('/api/reading/library?filter=anything').status_code, 422)
