"""Cloud plan lifecycle with an isolated DB and an HTTP-level GitHub simulator."""
import asyncio
import base64
import copy
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.core import Problem, digest
from plans.api import register
from plans.github import GitHubContent
from plans.github_store import GitHubPlans
from plans.store import Plans, TABLES
B = {'title':'经济学','goal':'理解经济新闻','level':'零基础','weeks':2,'sessions':1,'minutes':20}
D = {'prerequisites':'无需先修','stages':[{'title':'基础','goal':'解释概念'}],
     'lessons':[{'number':n,'topic':'主题'+str(n),'goal':'解释概念','exercise':'举例','assessment':'说明边界','stage':1,
                 'kind':'review' if n==2 else 'lesson','minutes':20,'requires':[] if n==1 else [1]} for n in (1,2)]}
S = [{'title':'资料','content':'明确选择的教学摘要。 https://example.org/lesson'}]

def content(ctx):
    return f'# 第{ctx["lesson_no"]:03d}课：示范\n日期：{ctx["date"]}\n## 引导问题\n问题\n## 核心概念\n概念\n## 完整示范\n示范\n## 误区与边界\n边界\n## 练习\n练习\n\n---\n\n## 参考分析\n分析\n## 自查\n自查\n## 记忆提示\n提示\n[来源](https://example.org/lesson)'


class Repository:
    """Tracks reachable commits, atomic ref changes and injected network failures."""
    def __init__(self):
        self.head = 'a' * 40
        self.commits = {self.head: {'files': {'README.md': 'Content repository'}, 'parents': []}}
        self.trees = {}
        self.serial = 0
        self.ref_updates = 0
        self.fail_update = False
        self.lose_response = False
        self.race = False
        self.requests = []

    def sha(self):
        self.serial += 1
        return f'{self.serial:040x}'

    def __call__(self, req):
        self.requests.append(req)
        path = req.url.path.removeprefix('/repos/owner/courses').lstrip('/')
        data = json.loads(req.content) if req.content else {}
        if path == '': return httpx.Response(200, json={'default_branch':'main'})
        if path == 'git/matching-refs/heads/':return httpx.Response(200, json=[])
        if path == 'git/ref/heads/main':
            if self.head is None:return httpx.Response(409, json={'message':'Git Repository is empty'})
            return httpx.Response(200, json={'object': {'sha': self.head}})
        if path == 'contents/README.md' and req.method == 'PUT':
            assert self.head is None
            sha = self.sha(); self.head = sha
            self.commits[sha] = {'files':{'README.md':base64.b64decode(data['content']).decode()},'parents':[]}
            return httpx.Response(201, json={'commit':{'sha':sha}})
        if path.startswith('git/commits/'):
            sha = path.rsplit('/', 1)[1]
            return httpx.Response(200, json={'sha': sha, 'tree': {'sha': sha},
                                            'parents': [{'sha': p} for p in self.commits[sha]['parents']]})
        if path.startswith('compare/'):
            base, head = path[len('compare/'):].split('...')
            current = head
            while current != base and self.commits[current]['parents']:
                current = self.commits[current]['parents'][0]
            return httpx.Response(200, json={'status':'ahead' if current == base else 'diverged'})
        if path.startswith('contents/'):
            ref = req.url.params.get('ref', self.head)
            if ref == 'main': ref = self.head
            files = self.commits[ref]['files']
            relative = path[len('contents/'):]
            if relative in files:
                return httpx.Response(200, json={'type': 'file', 'encoding': 'base64',
                    'content': base64.b64encode(files[relative].encode()).decode(),
                    'sha': digest(files[relative])})
            if any(p.startswith(relative+'/') for p in files):
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={'message': 'Not Found'})
        if path == 'git/trees':
            files = dict(self.commits[data['base_tree']]['files'])
            files.update({p['path']: p['content'] for p in data['tree']})
            sha = self.sha(); self.trees[sha] = files
            return httpx.Response(201, json={'sha': sha})
        if path == 'git/commits':
            sha = self.sha()
            self.commits[sha] = {'files': self.trees[data['tree']], 'parents': data['parents']}
            return httpx.Response(201, json={'sha': sha})
        if path == 'git/refs/heads/main':
            self.assert_safe(data)
            if self.fail_update:
                return httpx.Response(503, json={'message': 'Temporary upstream error: SECRET'})
            if self.race:
                self.race = False
                sha = self.sha()
                self.commits[sha] = {'files': dict(self.commits[self.head]['files'], unrelated='external'), 'parents': [self.head]}
                self.head = sha
            if self.commits[data['sha']]['parents'] != [self.head]:
                return httpx.Response(422, json={'message': 'Not a fast forward'})
            self.head = data['sha']; self.ref_updates += 1
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout('secret must not leak', request=req)
            return httpx.Response(200, json={'object': {'sha': self.head}})
        raise AssertionError((req.method, str(req.url)))

    @staticmethod
    def assert_safe(data):
        assert data['force'] is False, 'Never force-push content'


class SQLitePlans(GitHubPlans):
    """Only the DB boundary differs; publication and GitHub code are real."""
    mutex = threading.RLock()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_file, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()

    @contextmanager
    def database_lock(self, name, blocking=True):
        with self.mutex: yield


class LocalStorageCompatibility(unittest.TestCase):
    def test_local_publication_and_reading_still_use_local_files(self):
        class LocalPlans(Plans):
            conn = SQLitePlans.conn
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LocalPlans(root,root/'runtime');store.db_file=root/'test.db'
            with store.conn() as c:c.executescript(TABLES)
            draft=store.draft({'brief':B,'document':D})
            pid=store.adopt(draft['id'],'adopt')['plan_id']
            store.save_sources(pid,S);ctx=store.course_context(pid)
            draft=store.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
            result=store.publish_course(draft['id'],'course')
            self.assertTrue(Path(result['path']).is_file())
            self.assertIn('核心概念',store.read_course(pid,1)['content'])


class GitHubPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repository()
        self.content = GitHubContent('owner/courses', 'main', 'TEST_ONLY_TOKEN',
            transport=httpx.MockTransport(self.repo))
        self.db_file = Path(self.tmp.name)/'test.db'
        self.s = self.new_store()
        self.s.initialize()

    def new_store(self):
        s = SQLitePlans('/nonexistent-learning-root', '/nonexistent-runtime', self.content)
        s.db_file = self.db_file
        return s

    def adopt(self):
        d = self.s.draft({'brief': B, 'document': D})
        return self.s.adopt(d['id'], d['id'])['plan_id']

    def draft_course(self, pid):
        self.s.save_sources(pid, S)
        ctx = self.s.course_context(pid)
        return self.s.course_draft(ctx, content(ctx), '摘要 [来源](https://example.org/lesson)')

    def test_publish_and_read_without_any_content_directory(self):
        pid = self.adopt(); d = self.draft_course(pid)
        before = self.repo.ref_updates
        result = self.s.publish_course(d['id'], 'publish')
        self.assertEqual(self.repo.ref_updates, before+1)
        self.assertEqual(result['storage'], 'github')
        self.assertTrue(result['github_url'].startswith('https://github.com/owner/courses/blob/'))
        reading = self.new_store().read_course(pid, 1)
        self.assertIn('核心概念', reading['content'])
        self.assertIn('对应课程', reading['sources'])
        self.assertEqual(self.s.publish_course(d['id'], 'publish'), result)
        self.assertEqual(self.repo.ref_updates, before+1)

    def test_empty_repository_is_initialized_only_when_publishing(self):
        self.repo.head = None
        d = self.s.draft({'brief':B,'document':D})
        self.assertIsNone(self.repo.head)
        self.s.adopt(d['id'], 'first-adoption')
        self.assertIsNotNone(self.repo.head)
        self.assertIn('README.md', self.repo.commits[self.repo.head]['files'])

    def test_ref_failure_keeps_draft_and_restart_recovers(self):
        pid = self.adopt(); d = self.draft_course(pid)
        before = self.repo.head; self.repo.fail_update = True
        with self.assertRaises(Problem) as raised:
            self.s.publish_course(d['id'], 'pending')
        self.assertNotIn('SECRET', raised.exception.message)
        self.assertEqual(self.repo.head, before)
        self.assertEqual(self.s.lessons(pid), [])
        self.assertEqual(self.s.read_draft(d['id'])['state'], 'ready')
        self.repo.fail_update = False
        restarted = self.new_store(); restarted.initialize()
        self.assertEqual(len(restarted.lessons(pid)), 1)
        self.assertIn('核心概念', restarted.read_course(pid, 1)['content'])

    def test_lost_success_response_does_not_duplicate_commit(self):
        pid = self.adopt(); d = self.draft_course(pid)
        before = self.repo.ref_updates; self.repo.lose_response = True
        with self.assertRaises(Problem): self.s.publish_course(d['id'], 'lost')
        restarted = self.new_store(); restarted.initialize()
        self.assertEqual(self.repo.ref_updates, before+1)
        self.assertEqual(len(restarted.lessons(pid)), 1)

    def test_database_failure_after_github_commit_is_recoverable(self):
        pid = self.adopt(); d = self.draft_course(pid)
        original = self.s.conn
        class Connection:
            def __init__(self, wrapped): self.wrapped = wrapped
            def execute(self, sql, params=()):
                if sql.startswith('INSERT INTO learning_lessons '): raise RuntimeError('Simulated database interruption')
                return self.wrapped.execute(sql, params)
        @contextmanager
        def interrupted():
            with original() as c: yield Connection(c)
        before = self.repo.ref_updates
        with patch.object(self.s, 'conn', interrupted), self.assertRaises(RuntimeError):
            self.s.publish_course(d['id'], 'db-failure')
        self.assertEqual(self.s.lessons(pid), [])
        self.new_store().initialize()
        self.assertEqual(len(self.s.lessons(pid)), 1)
        self.assertEqual(self.repo.ref_updates, before+1)

    def test_concurrent_plan_adoption_allocates_unique_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids = list(pool.map(lambda _: self.adopt(), range(3)))
        self.assertEqual(len(set(ids)), 3)

    def test_credentials_or_branch_change_does_not_retarget_existing_plans(self):
        self.adopt()
        changed = self.new_store()
        changed.content = GitHubContent('owner/other', 'main', 'TEST_TOKEN')
        with self.assertRaises(Problem): changed.initialize()

    def test_branch_race_rebases_without_losing_unrelated_files(self):
        pid = self.adopt(); d = self.draft_course(pid); self.repo.race = True
        with self.assertRaises(Problem): self.s.publish_course(d['id'], 'race')
        with self.s.lock(): self.s.recover_locked()
        self.assertEqual(self.repo.commits[self.repo.head]['files']['unrelated'], 'external')
        self.assertEqual(len(self.s.lessons(pid)), 1)

    def test_changed_dependency_blocks_pending_course_publication(self):
        pid = self.adopt(); d = self.draft_course(pid)
        self.repo.fail_update = True
        with self.assertRaises(Problem):self.s.publish_course(d['id'], 'guarded')
        self.repo.fail_update = False
        old = self.repo.head; new = self.repo.sha()
        files = dict(self.repo.commits[old]['files'])
        files[self.s.base(pid)+'/学习规划.md'] += '\nChanged teaching plan'
        self.repo.commits[new] = {'files':files, 'parents':[old]};self.repo.head = new
        with self.assertRaises(Problem):
            with self.s.lock():self.s.recover_locked()
        self.assertEqual(self.repo.head, new)
        self.assertEqual(self.s.lessons(pid), [])

    def test_recovery_recognizes_commit_even_after_later_external_commit(self):
        pid = self.adopt(); d = self.draft_course(pid)
        self.repo.lose_response = True
        with self.assertRaises(Problem):self.s.publish_course(d['id'], 'lost-then-moved')
        published = self.repo.head; new = self.repo.sha()
        self.repo.commits[new] = {'files':dict(self.repo.commits[published]['files'], unrelated='later edit'), 'parents':[published]}
        self.repo.head = new; before = self.repo.ref_updates
        self.new_store().initialize()
        self.assertEqual(self.repo.head, new)
        self.assertEqual(self.repo.ref_updates, before)
        self.assertEqual(self.s.lessons(pid)[0]['commit_sha'], published)

    def test_external_change_is_never_overwritten(self):
        pid = self.adopt(); rel = self.s.base(pid)+'/学习规划.md'
        old = self.repo.head; new = self.repo.sha()
        files = dict(self.repo.commits[old]['files']); files[rel] += '\nExternal edit'
        self.repo.commits[new] = {'files': files, 'parents': [old]}; self.repo.head = new
        with self.assertRaises(Problem): self.s.save_sources(pid, S)
        self.assertTrue(self.repo.commits[self.repo.head]['files'][rel].endswith('External edit'))

    def test_reads_are_pinned_and_feedback_stays_in_database(self):
        pid = self.adopt(); d = self.draft_course(pid)
        self.s.publish_course(d['id'], 'p')
        baseline = self.s.read_course(pid, 1)['content']
        head = self.repo.head; new = self.repo.sha()
        files = dict(self.repo.commits[head]['files'])
        files[self.s.base(pid)+'/'+self.s.lessons(pid)[0]['path']] = 'external revision'
        self.repo.commits[new] = {'files': files, 'parents': [head]}; self.repo.head = new
        self.assertEqual(self.s.read_course(pid, 1)['content'], baseline)
        before = self.repo.ref_updates
        self.s.feedback(pid, 1, {'state': 'completed', 'comment': 'PRIVATE NOTE'}, 'feedback')
        self.assertEqual(self.repo.ref_updates, before)
        self.assertEqual(self.s.lessons(pid)[0]['learning_state'], 'completed')
        self.assertNotIn('PRIVATE NOTE', json.dumps(files))

    def test_rejects_path_escape_and_never_logs_credentials(self):
        for path in ('../secret', '/secret', '学习计划/../secret', '学习计划/a\\b'):
            with self.assertRaises(Problem): self.content.read_text(path)
        for req in self.repo.requests:
            self.assertNotIn('TEST_ONLY_TOKEN', str(req.url))

    def test_full_generation_publish_and_read_api(self):
        app = FastAPI()
        @app.exception_handler(Problem)
        async def problem(request, exc):
            from fastapi.responses import JSONResponse
            return JSONResponse({'message': exc.message}, status_code=exc.status)
        with patch('plans.api.make_store', return_value=self.s):
            store, generator = register(app, '/missing', '/missing')
        async def model(messages, config):
            ctx = json.loads(messages[1]['content'])
            yield {'text': json.dumps(D) if 'schema' in ctx else
                content(ctx)+'\n<!-- COPILOT_SOURCES -->\n摘要 [来源](https://example.org/lesson)'}
            yield {'done': True}
        generator.transport = model
        with TestClient(app) as client:
            def post(path, data):
                r = client.post('/api/plans'+path, json={'data': data}, headers={'X-Copilot-Request': '1'})
                self.assertEqual(r.status_code, 200, r.text)
                return r.json()
            def generate(body):
                import time
                a = post('/generate', body)
                for _ in range(200):
                    r = client.get('/api/plans/attempts/'+a['id']).json()
                    if r['state'] not in ('queued', 'generating'): break
                    time.sleep(.01)
                self.assertEqual(r['state'], 'ready', r)
                return client.get('/api/plans/drafts/'+r['draft_id']).json()
            d = generate({'key': 'plan', 'kind': 'plan', 'brief': B})
            pid = post('/drafts/'+d['id']+'/adopt', {'key': 'a', 'expected_hash': d['content_hash']})['plan_id']
            post('/'+pid+'/sources', {'entries': S})
            d = generate({'key': 'course', 'kind': 'course', 'plan_id': pid})
            post('/drafts/'+d['id']+'/publish', {'key': 'p', 'expected_hash': d['content_hash']})
            r = client.get('/api/plans/'+pid+'/lessons/1')
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn('核心概念', r.json()['content'])
            self.assertIn('github_url', r.json())
            post('/'+pid+'/lessons/1/feedback', {'key': 'f', 'state': 'completed', 'comment': '已练习'})


@unittest.skipUnless(os.getenv('TEST_GITHUB_PG_DSN'), 'Set TEST_GITHUB_PG_DSN to an isolated local PostgreSQL')
class PostgreSQLPlanTests(GitHubPlanTests):
    def setUp(self):
        import db
        import psycopg2
        import uuid
        self.dsn = os.environ['TEST_GITHUB_PG_DSN']
        if not ('host=127.0.0.1' in self.dsn or 'host=localhost' in self.dsn):
            raise RuntimeError('PostgreSQL tests require an explicit localhost DSN')
        self.schema = 'github_test_'+uuid.uuid4().hex
        c = psycopg2.connect(self.dsn); c.autocommit = True
        c.cursor().execute('CREATE SCHEMA '+self.schema); c.close()
        def cleanup():
            c = psycopg2.connect(self.dsn); c.autocommit = True
            c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE'); c.close()
        self.addCleanup(cleanup)
        original = db.connect
        patcher = patch('db.connect', lambda *args, **kwargs: original(self.dsn+' options=-csearch_path='+self.schema))
        patcher.start(); self.addCleanup(patcher.stop)
        super().setUp()

    def new_store(self):
        return GitHubPlans('/nonexistent-learning-root', '/nonexistent-runtime', self.content)


if __name__ == '__main__': unittest.main()
