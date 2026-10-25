"""Private note drafts: real isolated PostgreSQL, without a running service or model."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import patch
import uuid

import db
from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2

from test_legacy_cloud_schema import PostgreSQLFixture


class StudyNotesTests(PostgreSQLFixture):
    def setUp(self):
        self.raw_connect = db.connect
        super().setUp()
        from study_notes import register
        self.register = register
        self.app = FastAPI()
        register(self.app)
        self.client = TestClient(self.app, base_url='http://localhost')
        self.addCleanup(self.client.close)
        self.headers = {'X-Copilot-Request': '1'}
        self.path = '/api/study-notes/biaoda/Day%20001.md'

    def body(self, **updates):
        return {'notes': '暂存笔记', 'answers': {'practice-1': '我的练习答案'},
                'version': 'a' * 64, 'revision': 0, 'key': 'draft-request-one', **updates}

    def put(self, body=None, path=None, headers=None):
        return self.client.put(path or self.path, json=body or self.body(),
                               headers=self.headers if headers is None else headers)

    def test_notebook_lists_saved_drafts_without_requiring_course_completion(self):
        self.put(self.body(notes='还没学完的证据笔记', answers={'q1': '先观察再解释'}))
        response = self.client.get('/api/study-notes')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('no-store', response.headers.get('cache-control', ''))
        data = response.json()
        self.assertEqual(data['total'], 1)
        note = data['items'][0]
        self.assertEqual((note['kind'], note['course_id']), ('biaoda', 'Day 001.md'))
        self.assertEqual(note['preview'], '还没学完的证据笔记')
        self.assertEqual(note['answer_count'], 1)
        self.assertEqual(note['target'], {'kind': 'study', 'module': 'biaoda', 'course': 'Day 001.md'})
        self.assertNotIn('answers', note)
        self.assertNotIn('request_key', note)
        self.assertNotIn('completed_at', note)
        with db.connect() as connection:
            self.assertIsNone(connection.execute("SELECT to_regclass('study_learning_records')").fetchone()[0])

    def test_notebook_searches_answers_filters_modules_and_treats_wildcards_literally(self):
        self.put(self.body(notes='', answers={'q1': '判断依据 50%_增长'}))
        self.put(self.body(notes='另一篇笔记', key='another-note-key'), '/api/study-notes/yingyu/Day%20002.md')
        self.assertEqual(self.client.get('/api/study-notes', params={'q': '判断依据'}).json()['total'], 1)
        literal = self.client.get('/api/study-notes', params={'q': '%_'})
        self.assertEqual(literal.json()['total'], 1)
        self.assertIn('50%_增长', literal.json()['items'][0]['preview'])
        english = self.client.get('/api/study-notes', params={'kind': 'yingyu'}).json()
        self.assertEqual(english['total'], 1)
        self.assertEqual(english['items'][0]['kind'], 'yingyu')
        self.assertEqual(self.client.get('/api/study-notes', params={'kind': 'invalid'}).status_code, 422)

    def test_notebook_paginates_stably_and_omits_empty_notes(self):
        for index in range(5):
            self.put(self.body(notes=f'笔记 {index}', key=f'notebook-key-{index}'), f'/api/study-notes/renzhi/{index+1}')
        self.put(self.body(notes=' \n\t', answers={'q1': ' \r\n'}, key='empty-note-key'))
        first = self.client.get('/api/study-notes', params={'page_size': 2}).json()
        second = self.client.get('/api/study-notes', params={'page_size': 2, 'page': 2}).json()
        self.assertEqual(first['total'], 5)
        self.assertEqual((len(first['items']), len(second['items'])), (2, 2))
        self.assertFalse({n['course_id'] for n in first['items']} & {n['course_id'] for n in second['items']})
        self.assertEqual(self.client.get('/api/study-notes', params={'page': 0}).status_code, 422)
        self.assertEqual(self.client.get('/api/study-notes', params={'page_size': 101}).status_code, 422)

    def test_notebook_is_scoped_to_the_current_database_tenant(self):
        self.put(self.body(notes='本人笔记'))
        other = 'notebook_other_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as connection:
            connection.cursor().execute('CREATE SCHEMA ' + other)
        try:
            with patch('db.connect', lambda *a, **kw: self.raw_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                self.put(self.body(notes='另一个人的私人笔记'))
                listing = self.client.get('/api/study-notes').json()
                self.assertEqual([n['preview'] for n in listing['items']], ['另一个人的私人笔记'])
            listing = self.client.get('/api/study-notes').json()
            self.assertEqual([n['preview'] for n in listing['items']], ['本人笔记'])
        finally:
            with psycopg2.connect(self.dsn) as connection:
                connection.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')

    def test_first_get_and_put_create_missing_tenant_table_and_public_read_survives_app_restart(self):
        with db.connect() as connection:
            self.assertIsNone(connection.execute("SELECT to_regclass('course_study_notes')").fetchone()[0])
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json())
        first = self.put()
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()
        self.assertEqual(saved['notes'], self.body()['notes'])
        self.assertEqual(saved['answers'], self.body()['answers'])
        self.assertEqual(saved['version'], 'a' * 64)
        self.assertEqual(saved['revision'], 1)
        self.assertTrue(saved['updated_at'])
        self.assertNotIn('request_key', saved)
        self.assertNotIn('request_hash', saved)
        self.assertNotIn('key', saved)
        self.assertIn('no-store', first.headers.get('cache-control', ''))

        restarted = FastAPI()
        self.register(restarted)
        with TestClient(restarted, base_url='http://localhost') as client:
            read = client.get(self.path)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json(), saved)
        self.assertIn('no-store', read.headers.get('cache-control', ''))

    def test_first_put_alone_can_create_the_table_and_explicit_initialize_is_repeatable(self):
        first = self.put()
        self.assertEqual(first.status_code, 200, first.text)
        from study_notes import initialize
        initialize()
        with db.connect() as connection:
            initialize(connection)
        self.assertEqual(self.client.get(self.path).json(), first.json())

    def test_note_kinds_courses_and_nested_plan_course_ids_are_independent(self):
        targets = ['/api/study-notes/yingyu/Day%20001.md', self.path,
                   '/api/study-notes/biaoda/Day%20002.md', '/api/study-notes/renzhi/1',
                   '/api/study-notes/plan/plan-20261018-001/1',
                   '/api/study-notes/plan/plan-20261018-001/2']
        for index, target in enumerate(targets):
            response = self.put(self.body(notes=f'课程笔记 {index}', key=f'isolated-{index}'), path=target)
            self.assertEqual(response.status_code, 200, response.text)
        for index, target in enumerate(targets):
            self.assertEqual(self.client.get(target).json()['notes'], f'课程笔记 {index}')
        self.assertIsNone(self.client.get('/api/study-notes/yingyu/Day%20002.md').json())

    def test_same_key_retry_is_idempotent_and_changed_replay_or_stale_tab_cannot_overwrite(self):
        original = self.body()
        first = self.put(original)
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()
        retry = self.put(original)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), saved)
        for change in ({'notes': 'changed retry'}, {'answers': {'practice-1': 'changed'}},
                       {'version': 'b' * 64}, {'revision': 1}):
            with self.subTest(change=change):
                self.assertEqual(self.put({**original, **change}).status_code, 409)
        stale = self.put(self.body(notes='另一个旧标签页', key='draft-other-tab'))
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.client.get(self.path).json(), saved)

        updated = self.put(self.body(notes='继续编辑', answers={'practice-2': '新答案'},
                                     revision=1, key='draft-request-two'))
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['revision'], 2)
        self.assertEqual(updated.json()['notes'], '继续编辑')
        self.assertEqual(updated.json()['answers'], {'practice-2': '新答案'})

    def test_simultaneous_first_saves_have_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda key: self.put(self.body(key=key)),
                                      ['simultaneous-one', 'simultaneous-two']))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(self.client.get(self.path).json()['revision'], 1)

    def test_untrusted_note_and_answer_content_remains_plain_text(self):
        text = '<script>alert("note")</script>\n<img src=x onerror=alert(1)>\n**原文** & 中文'
        body = self.body(notes=text, answers={'<img onerror=alert(1)>': text})
        result = self.put(body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['notes'], text)
        self.assertEqual(result.json()['answers'], body['answers'])
        self.assertEqual(self.client.get(self.path).json(), result.json())
        self.assertIn('application/json', result.headers.get('content-type', ''))

    def test_invalid_fields_and_input_limits_are_rejected_without_creating_notes(self):
        invalid = [
            {'unexpected': 'ignored?'}, {'notes': 'x' * 10001}, {'notes': 123},
            {'answers': {'q': 'x' * 10001}}, {'answers': {str(i): '' for i in range(101)}},
            {'answers': {str(i): 'x' * 10000 for i in range(7)}}, {'answers': {'q': 1}},
            {'answers': []}, {'version': 'a' * 63}, {'version': 'g' * 64},
            {'revision': -1}, {'revision': True}, {'revision': 0.5},
            {'key': 'short'}, {'key': 'x' * 161},
        ]
        for update in invalid:
            with self.subTest(update=list(update)):
                response = self.put(self.body(**update))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.client.get(self.path).json())
        self.assertEqual(self.put(path='/api/study-notes/unknown/course').status_code, 422)

    def test_maximum_lengths_and_empty_draft_are_valid(self):
        maximum = self.body(notes='笔' * 10000, answers={str(i): '答' * 10000 for i in range(6)})
        response = self.put(maximum)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['answers'], maximum['answers'])
        cleared = self.put(self.body(notes='', answers={}, revision=1, key='clear-draft-key'))
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()['notes'], '')
        self.assertEqual(cleared.json()['answers'], {})

    def test_cross_site_and_unmarked_writes_are_forbidden(self):
        for headers in ({}, {**self.headers, 'Origin': 'https://evil.example'},
                        {**self.headers, 'Sec-Fetch-Site': 'cross-site'},
                        {**self.headers, 'Origin': 'null'}):
            with self.subTest(headers=headers):
                response = self.put(headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
        response = self.put(headers={**self.headers, 'Origin': 'http://localhost',
                                     'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_saving_notes_neither_completes_pending_courses_nor_changes_existing_completion_notes(self):
        # The draft route must not insert or update any completion/feedback record.
        with db.connect() as connection:
            connection.executescript('''
                CREATE TABLE study_learning_records (module_id TEXT, filename TEXT, data TEXT);
                CREATE TABLE copilot_learning_records (lesson_no INTEGER, data TEXT);
                CREATE TABLE learning_feedback (plan_id TEXT, lesson_no INTEGER, data TEXT);
            ''')
            connection.execute('INSERT INTO study_learning_records VALUES (?,?,?)',
                               ('yingyu', 'Day 001.md', json.dumps({'summary_text': '已完成课程原笔记',
                                                                  'completed_at': '2026-10-15T10:00:00+08:00'})))
            connection.execute('INSERT INTO copilot_learning_records VALUES (?,?)',
                               (1, json.dumps({'summary_text': '认知原总结', 'time_spent_seconds': 120})))
            connection.execute('INSERT INTO learning_feedback VALUES (?,?,?)',
                               ('plan-20261018-001', 1, json.dumps({'state': 'completed', 'comment': '原反馈'})))

        def completion_snapshot():
            with db.connect() as connection:
                return {table: [dict(row) for row in connection.execute(f'SELECT * FROM {table}').fetchall()]
                        for table in ('study_learning_records', 'copilot_learning_records', 'learning_feedback')}

        before = completion_snapshot()
        paths = [self.path, '/api/study-notes/yingyu/Day%20001.md', '/api/study-notes/renzhi/1',
                 '/api/study-notes/renzhi/2', '/api/study-notes/plan/plan-20261018-001/1',
                 '/api/study-notes/plan/plan-20261018-001/2']
        for index, path in enumerate(paths):
            response = self.put(self.body(notes='未完成也可暂存', key=f'pending-note-{index}'), path=path)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(completion_snapshot(), before)

    def test_account_schemas_do_not_share_notes(self):
        from tenancy import current_user
        other_schema = 'study_notes_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as connection:
            connection.cursor().execute('CREATE SCHEMA ' + other_schema)

        def drop_other():
            with psycopg2.connect(self.dsn) as connection:
                connection.cursor().execute('DROP SCHEMA ' + other_schema + ' CASCADE')
        self.addCleanup(drop_other)

        with patch('db.connect', lambda *args, **kwargs: self.raw_connect(self.dsn)):
            token = current_user.set({'schema_name': self.schema})
            try:
                first = self.put(self.body(notes='甲账号私有笔记'))
                self.assertEqual(first.status_code, 200, first.text)
            finally:
                current_user.reset(token)
            token = current_user.set({'schema_name': other_schema})
            try:
                self.assertIsNone(self.client.get(self.path).json())
                second = self.put(self.body(notes='乙账号私有笔记'))
                self.assertEqual(second.status_code, 200, second.text)
                self.assertEqual(second.json()['revision'], 1)
            finally:
                current_user.reset(token)
            token = current_user.set({'schema_name': self.schema})
            try:
                self.assertEqual(self.client.get(self.path).json(), first.json())
            finally:
                current_user.reset(token)
