"""Plan publications journaled in PostgreSQL and committed directly to GitHub."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from copilot.core import digest, encoded, fail, now, Problem
from .github import GitHubContent
from .store import Plans, TABLES


class GitHubPlans(Plans):
    remote = True

    def __init__(self, root, db, content=None):
        super().__init__(root, db)
        self.content = content or GitHubContent.from_env()
        self.local = threading.local()

    @contextmanager
    def database_lock(self, name, blocking=True):
        # A dedicated transaction holds the lock while journal writes use separate
        # short transactions. Rollback/disconnect releases it, including via poolers.
        with self.conn() as c:
            identity = int(digest(name)[:15], 16)
            fn = 'pg_advisory_xact_lock' if blocking else 'pg_try_advisory_xact_lock'
            result = c.execute(f'SELECT {fn}(?)', (identity,)).fetchone()
            if not blocking and not result[0]: fail('busy', '另一个生成任务正在运行。')
            yield

    @contextmanager
    def lock(self):
        if getattr(self.local, 'locked', False):
            yield
            return
        with self.database_lock('learning-plan-publications'):
            self.local.locked = True
            self.local.head = None
            try:
                # Complete interrupted publications before any new mutation.
                self.recover_locked()
                yield
            finally:
                self.local.locked = False
                self.local.head = None

    @contextmanager
    def generation_gate(self):
        with self.database_lock('learning-plan-generation', blocking=False): yield

    def ref(self):
        if not getattr(self.local, 'locked', False): return self.content.head()
        if self.local.head is None: self.local.head = self.content.head()
        return self.local.head

    def read_text(self, relative, ref=None):
        return self.content.read_text(relative, ref or self.ref())

    def exists(self, relative):
        return self.content.exists(relative, self.ref())

    def hash(self, relative):
        text = self.content.read_text(relative, self.ref(), missing=True)
        return digest(text) if text is not None else None

    def file_location(self, relative):
        self.content.path(relative)
        return relative

    def path(self, relative):
        fail('github_storage', 'GitHub 模式不使用本地课程路径。', 409)

    def initialize(self):
        self.content.validate()
        # Schema installation is additive; never invokes SQLite backup or touches disk.
        with self.conn() as c: c.executescript(TABLES)
        binding = {'repository': self.content.repository, 'branch': self.content.branch}
        with self.database_lock('learning-plan-publications'):
            stored = [x for x in self.rows('learning_settings') if x['id'] == 'content-storage']
            if stored and stored[0]['binding'] != binding:
                fail('github_config', '内容仓库或分支与已登记数据不一致，请先完成迁移。', 503)
            self.put('learning_settings', 'content-storage', {'id': 'content-storage', 'binding': binding})
        # Failed GitHub writes remain retryable without making existing reading unavailable.
        try:
            with self.lock(): pass
        except Problem as exc:
            if exc.code not in ('github_unavailable', 'github_access', 'github_conflict', 'conflict'): raise
        with self.conn() as c:
            for row in c.execute('SELECT id,data FROM learning_ai_attempts').fetchall():
                attempt = json.loads(row['data'])
                if attempt['state'] in ('queued', 'generating'):
                    attempt.update(state='failed', phase='failed', error='服务已重启，生成中断；草稿已保留，请重新生成。')
                    c.execute('UPDATE learning_ai_attempts SET data=? WHERE id=?', (encoded(attempt), row['id']))

    def get_setting(self, key, default=''):
        with self.conn() as c:
            # Some earlier cloud schemas used id/data instead of key/value. In that
            # case use the model's environment configuration, without invalid SQL.
            if isinstance(c, sqlite3.Connection):
                columns = {r[1] for r in c.execute('PRAGMA table_info(copilot_settings)')}
            else:
                columns = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='copilot_settings'")}
            if not {'key', 'value'} <= columns: return default
            row = c.execute('SELECT value FROM copilot_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def publish(self, key, request, files, sql, result):
        replay = self.replay(key, request)
        if replay is not None: return replay
        if files and self.ref() is None:
            self.content.bootstrap()
            self.local.head = None
        changes = {rel: {'before': self.hash(rel), 'text': value, 'after': digest(value)}
                   for rel, value in files.items()}
        guards = {}
        for pid in {rel.split('/')[1] for rel in files}:
            with self.conn() as c:
                row = c.execute('SELECT data FROM learning_plans WHERE id=?', (pid,)).fetchone()
            if row:
                for rel in json.loads(row[0]).get('hashes', {}): guards[rel] = self.hash(rel)
        journal = {'state': 'pending', 'request': digest(encoded(request)), 'files': changes,
                   'sql': sql, 'result': result, 'backend': 'github', 'created_at': now(),
                   'repository': self.content.repository, 'branch': self.content.branch, 'guards': guards}
        self.put('learning_publications', key, journal)
        self.finish(key, journal)
        return journal['result']

    def finish(self, key, journal):
        if journal.get('backend') != 'github':
            fail('conflict', '发现旧本地发布任务，请先在原存储模式完成恢复。')
        if (journal['repository'], journal['branch']) != (self.content.repository, self.content.branch):
            fail('conflict', '发布任务属于其他内容仓库，不能自动重放。')
        if journal['files']:
            head = self.content.head()
            candidate = journal.get('commit_sha')
            reached = candidate and self.content.contains(candidate, head)
            if not reached:
                # A moved branch can be rebased only if every target still matches
                # the original baseline. Manual changes are never overwritten.
                for rel, expected in journal.get('guards', {}).items():
                    current = self.content.read_text(rel, head, missing=True)
                    if (digest(current) if current is not None else None) != expected:
                        fail('conflict', 'GitHub 规划或备课资料已变化，请人工核对：'+rel)
                for rel, change in journal['files'].items():
                    current = self.content.read_text(rel, head, missing=True)
                    actual = digest(current) if current is not None else None
                    if actual != change['before']: fail('conflict', 'GitHub 文件已被修改，请人工核对：'+rel)
                if not candidate or journal.get('parent_sha') != head:
                    candidate = self.content.prepare(head,
                        {rel: change['text'] for rel, change in journal['files'].items()}, key)
                    journal.update(commit_sha=candidate, parent_sha=head)
                    # Persist before touching the branch, so a lost success response
                    # is recoverable by testing commit ancestry, not guessing hashes.
                    self.put('learning_publications', key, journal)
                self.content.advance(candidate)
            # Verify files at the immutable candidate before recording success.
            for rel, change in journal['files'].items():
                if digest(self.content.read_text(rel, candidate)) != change['after']:
                    fail('conflict', 'GitHub 提交校验失败，请人工核对。')
            self.local.head = None
            result = journal['result']
            result.update(storage='github', commit_sha=candidate)
            if result.get('path'): result['github_url'] = self.content.url(result['path'], candidate)
            elif result.get('plan_id'):
                result['github_url'] = self.content.url(self.base(result['plan_id'])+'/学习规划.md', candidate)
        # Applying these SQL effects and marking the journal done is one DB transaction.
        with self.conn() as c:
            for statement, parameters in journal['sql']:
                values = list(parameters)
                if statement.startswith('INSERT INTO learning_lessons '):
                    lesson = json.loads(values[2])
                    lesson.update(storage='github', commit_sha=journal['commit_sha'])
                    values[2] = encoded(lesson)
                c.execute(statement, values)
            journal['state'] = 'done'
            c.execute('UPDATE learning_publications SET data=? WHERE id=?', (encoded(journal), key))

    def recover_locked(self):
        with self.conn() as c:
            rows = c.execute('SELECT id,data FROM learning_publications').fetchall()
        pending = [(r['id'], json.loads(r['data'])) for r in rows if json.loads(r['data'])['state'] == 'pending']
        for key, journal in sorted(pending, key=lambda item: item[1].get('created_at', '')):
            self.finish(key, journal)

    def read_course(self, pid, number):
        self.plan(pid)
        lesson = next((x for x in self.lessons(pid) if x['lesson_no'] == number), None)
        if not lesson: fail('not_found', '课程不存在。', 404)
        if not lesson.get('commit_sha'):
            fail('migration_required', '这节历史课程尚未迁入 GitHub，请先迁移或创建新计划。', 409)
        base = self.base(pid); ref = lesson['commit_sha']
        return {'lesson': lesson, 'content': self.read_text(base+'/'+lesson['path'], ref),
                'sources': self.read_text(base+'/'+lesson['source'], ref),
                'github_url': self.content.url(base+'/'+lesson['path'], ref),
                'sources_github_url': self.content.url(base+'/'+lesson['source'], ref), 'commit_sha': ref}

    def feedback(self, pid, n, data, key):
        # Personal notes and high-frequency progress stay in the database.
        state = data.get('state'); comment = data.get('comment', '')
        if state not in ('completed', 'unknown') or not isinstance(comment, str) or len(comment) > 4000:
            fail('invalid', '学习反馈格式无效。', 422)
        request = {'op': 'feedback', 'plan_id': pid, 'lesson_no': n, 'state': state, 'comment': comment}
        with self.lock():
            replay = self.replay(key, request)
            if replay is not None: return replay
            self.plan(pid)
            lesson = next((x for x in self.lessons(pid) if x['lesson_no'] == n), None)
            if not lesson: fail('not_found', '课程不存在。', 404)
            lesson.update(learning_state=state, learning_label='本人确认完成' if state == 'completed' else '待本人反馈')
            feedback = {'state': state, 'comment': comment, 'date': now()}
            return self.publish(key, request, {}, [
                ('UPDATE learning_lessons SET data=? WHERE plan_id=? AND lesson_no=?', [encoded(lesson), pid, n]),
                ('INSERT INTO learning_feedback VALUES (?,?,?) ON CONFLICT(plan_id,lesson_no) DO UPDATE SET data=excluded.data',
                 [pid, n, encoded(feedback)])], feedback)


def make_store(root, db):
    backend = os.getenv('PLAN_CONTENT_BACKEND', 'local')
    if backend == 'github': return GitHubPlans(root, db)
    if backend != 'local': fail('config', 'PLAN_CONTENT_BACKEND 只能为 local 或 github。', 503)
    return Plans(root, db)
