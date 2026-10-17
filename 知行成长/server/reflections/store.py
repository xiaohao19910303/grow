"""轻量日常复盘存储：独立于旧全量同步的持久化、版本与可恢复的文件镜像。

复用 copilot 的 core 工具（digest/encoded/fail/now）与 plans 的共享写入锁
（`.plans/write.lock`），但表与文件白名单完全独立，不进入 `/api/data` 覆盖链路。
"""
import fcntl
import json
import os
import re
import db
import tempfile
import uuid
from contextlib import contextmanager, closing
from pathlib import Path

from copilot.core import digest, encoded, fail, now

REFLECTION_DIR = '执行复盘'
DAILY_DIR = '日常记录'
ID = re.compile(r'^ref-[0-9a-f]{32}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
PROMPT_KINDS = ('自由记录', '学习收获', '遇到困难', '决策回顾')
MAX_TEXT = 10000

TABLES = '''
CREATE TABLE IF NOT EXISTS reflection_entries (
    id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reflection_versions (
    key TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reflection_ai_attempts (
    id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reflection_operations (
    id TEXT PRIMARY KEY, data TEXT NOT NULL);
'''


def entry_path(entry_id, record_date):
    month = record_date[:7]
    return f'{REFLECTION_DIR}/{DAILY_DIR}/{month}/{entry_id}.md'


def render_markdown(entry):
    kind = entry.get('prompt_kind', '自由记录')
    tags = entry.get('tags') or []
    lines = [
        f'# 日常记录',
        '',
        f'- 编号：{entry["id"]}',
        f'- 日期：{entry["record_date"]}',
        f'- 方向：{kind}',
        f'- 版本：{entry["version"]}',
    ]
    if tags:
        lines.append(f'- 标签：{", ".join(tags)}')
    lines += [
        '',
        '## 记录',
        '',
        entry.get('raw_text', '').strip(),
    ]
    answers = entry.get('guided_answers') or {}
    if answers:
        lines += ['', '## 深入补充', '']
        for question, answer in answers.items():
            if not answer:
                continue
            lines += [f'- {question}', f'  {answer}']
    summary = entry.get('adopted_summary')
    if summary:
        lines += ['', '## 本人采用的整理', '']
        for section in summary.get('sections', []):
            kind_label = {'event': '发生的事情', 'understanding': '我目前的认识',
                          'next_step': '下一步想试什么'}.get(section.get('kind'), '补充')
            lines += [f'### {kind_label}', '', section.get('text', '').strip(), '']
        lines += [f'> 来源：AI 建议经本人确认采用（依据版本 {entry.get("summary_basis_version")}）。']
    lines += ['', '---', f'> 由知行成长日常记录生成 · 更新于 {entry.get("updated_at") or entry.get("created_at")}', '']
    return '\n'.join(lines)


class ReflectionsStore:
    def __init__(self, root, db):
        self.root = Path(root).absolute()
        self.db = Path(db)
        self.runtime = self.db / '.plans'
        self.startup_error = None
        self.remote = os.getenv('PLAN_CONTENT_BACKEND') == 'github'

    @contextmanager
    def conn(self):
        with closing(db.connect()) as c:
            with c:
                yield c

    def lock_id(self, name):
        from tenancy import current_user
        user = current_user.get()
        return int(digest((user['schema_name'] + ':' if user else '') + name)[:15], 16)

    @contextmanager
    def lock(self):
        if self.remote:
            with self.conn() as c:
                c.execute('SELECT pg_advisory_xact_lock(?)', (self.lock_id('reflection-writes'),))
                yield
            return
        if not self.root.is_dir():
            fail('unavailable', '学习磁盘不可用。', 503)
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / 'write.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    @contextmanager
    def generation_gate(self):
        if self.remote:
            with self.conn() as c:
                acquired = c.execute('SELECT pg_try_advisory_xact_lock(?)', (self.lock_id('learning-plan-generation'),)).fetchone()[0]
                if not acquired:
                    fail('generation_busy', '另一个 AI 任务正在运行。')
                yield
        else:
            with (self.db.parent / '.ai-generation.lock').open('a') as gate:
                try:
                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    fail('generation_busy', '另一个 AI 任务正在运行。')
                yield

    def path(self, relative):
        prefix = f'{REFLECTION_DIR}/{DAILY_DIR}/'
        if not isinstance(relative, str) or not relative.startswith(prefix):
            fail('invalid', '复盘文件路径无效。', 422)
        if '..' in Path(relative).parts:
            fail('invalid', '复盘文件路径无效。', 422)
        p = self.root / relative
        for part in (p, *p.parents):
            if part.is_symlink():
                fail('conflict', '复盘路径不能经过符号链接。')
            if part == self.root:
                break
        if not p.resolve().is_relative_to(self.root.resolve()):
            fail('conflict', '复盘路径越界。')
        return p

    def hash(self, relative):
        p = self.path(relative)
        return digest(p.read_bytes()) if p.exists() else None

    def expected_mirror(self, entry):
        # Legacy records are trusted only if the existing mirror exactly matches
        # the stored entry rendered today. Never adopt an arbitrary disk hash.
        expected = entry.get('mirror_hash') or digest(render_markdown(entry))
        if self.remote:
            return expected
        try:
            actual = self.hash(entry['path'])
        except OSError:
            fail('external_change', '本地文件无法读取，已停止覆盖。请先核对文件。')
        if actual != expected:
            fail('external_change', '本地文件已被修改或移走，已停止覆盖。请核对文件与原保存内容。')
        return expected

    def mirror_status(self, entry_id):
        entry = self.entry(entry_id)
        if self.remote:
            return {'id': entry_id, 'path': None, 'storage': 'database', 'conflict': False,
                    'saved_markdown': render_markdown(entry), 'file_markdown': None}
        p = self.path(entry['path'])
        content = None
        try:
            if p.exists():
                with p.open('rb') as stream:
                    raw = stream.read(200001)
                if len(raw) > 200000:
                    fail('external_change', '本地文件过大，请在文件编辑器中核对；系统未覆盖。')
                content = raw.decode('utf-8')
        except UnicodeError:
            fail('external_change', '文件已不是UTF-8文本，请在文件编辑器中核对；系统未覆盖。')
        except OSError:
            fail('external_change', '本地文件无法读取，请在文件编辑器中核对；系统未覆盖。')
        expected = entry.get('mirror_hash') or digest(render_markdown(entry))
        return {'id': entry_id, 'path': entry['path'],
                'conflict': content is None or digest(content) != expected,
                'saved_markdown': render_markdown(entry), 'file_markdown': content}

    def get(self, table, key):
        with self.conn() as c:
            row = c.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        if not row:
            fail('not_found', '记录不存在。', 404)
        return json.loads(row[0])

    def rows(self, table):
        with self.conn() as c:
            return [json.loads(r[0]) for r in c.execute(f'SELECT data FROM {table}')]

    def initialize(self):
        if not self.remote and (self.runtime / 'restore-pending.json').exists():
            fail('restore_pending', '存在未完成的恢复，请先处理恢复日志。', 503)
        with self.lock():
            with self.conn() as c:
                installed = True if self.remote else c.execute("SELECT 1 FROM sqlite_master WHERE name='reflection_entries'").fetchone()
            if not installed:
                from plans.backup import database_snapshot
                database_snapshot(self, self.runtime / f'before-reflection-{uuid.uuid4().hex}.db')
            with self.conn() as c:
                c.executescript(TABLES)
            with self.conn() as c:
                for row in c.execute('SELECT id,data FROM reflection_ai_attempts').fetchall():
                    a = json.loads(row['data'])
                    if a.get('status') in ('queued', 'generating'):
                        a.update(status='failed', error='服务重启导致生成中断；不会自动重试。', finished_at=now())
                        c.execute('UPDATE reflection_ai_attempts SET data=? WHERE id=?', (encoded(a), row['id']))
            self.recover_locked()
            if not self.remote:
                self._ensure_readme()

    def get_setting(self, key, default=''):
        """共享 copilot 的模型配置，复用其 settings 表。"""
        with self.conn() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='copilot_settings'").fetchone():
                return default
            row = c.execute('SELECT value FROM copilot_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _ensure_readme(self):
        readme = f'{REFLECTION_DIR}/{DAILY_DIR}/README.md'
        if self.hash(readme) is None:
            text = ('# 日常记录\n\n这是「知行成长」的轻量日常记录目录。\n\n'
                    '每天记下一件值得留下的小事，也可以晚些再写。\n\n'
                    '记录按创建月份归档，文件名使用稳定编号；正文修改不会迁移文件位置。\n'
                    '此处由应用自动维护，请勿手动新增或合并索引文件。\n')
            self._write_file(readme, text, None)

    def replay(self, key, request):
        with self.conn() as c:
            row = c.execute('SELECT data FROM reflection_operations WHERE id=?', (key,)).fetchone()
        if not row:
            return None
        op = json.loads(row[0])
        if op['request_hash'] != digest(encoded(request)):
            fail('conflict', '相同请求标识不能用于不同内容。')
        if op['state'] != 'done':
            fail('pending', '有未完成写入，请先检查恢复。')
        return op['result']

    def publish(self, key, request, files, records, result):
        """Caller holds the writer lock; cloud records and journal commit together."""
        if self.remote:
            previous = self.replay(key, request)
            if previous is not None:
                return previous
            op = {'id': key, 'state': 'done', 'request_hash': digest(encoded(request)),
                  'files': {}, 'result': result, 'created_at': now()}
            with self.conn() as c:
                for record in records:
                    c.execute(record['sql'], record['params'])
                c.execute('INSERT INTO reflection_operations VALUES (?,?)', (key, encoded(op)))
            return result
        with self.conn() as c:
            existing = c.execute('SELECT data FROM reflection_operations WHERE id=?', (key,)).fetchone()
        if existing:
            op = json.loads(existing[0])
            if op['request_hash'] != digest(encoded(request)):
                fail('conflict', '相同请求标识不能用于不同内容。')
            if op['state'] == 'done':
                return op['result']
            return self._resume(key)
        op = {'id': key, 'state': 'pending', 'request_hash': digest(encoded(request)),
              'files': files, 'records': records, 'result': result, 'created_at': now()}
        with self.conn() as c:
            c.execute('INSERT INTO reflection_operations VALUES (?,?)', (key, encoded(op)))
        return self._resume(key)

    def _resume(self, key):
        with self.conn() as c:
            row = c.execute('SELECT data FROM reflection_operations WHERE id=?', (key,)).fetchone()
        op = json.loads(row[0])
        # Preflight：文件目标当前哈希必须等于 old_hash 或已写成的 new_hash。
        for rel, change in op['files'].items():
            if self.hash(rel) not in (change['old'], change['new']):
                fail('conflict', f'文件已被外部修改：{rel}。')
        for rel, change in op['files'].items():
            if self.hash(rel) == change['new']:
                continue
            self._write_file(rel, change['content'], change['old'])
        with self.conn() as c:
            for record in op['records']:
                c.execute(record['sql'], record['params'])
            op['state'] = 'done'
            c.execute('UPDATE reflection_operations SET data=? WHERE id=?', (encoded(op), key))
        return op['result']

    def recover_locked(self):
        with self.conn() as c:
            keys = [r[0] for r in c.execute('SELECT id,data FROM reflection_operations') if json.loads(r[1]).get('state') == 'pending']
        if self.remote and keys:
            fail('migration_pending', '存在旧文件写入任务，请先完成迁移核对。', 503)
        for key in keys:
            self._resume(key)

    def _write_file(self, relative, content, old_hash):
        p = self.path(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.reflection-', dir=p.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if self.hash(relative) != old_hash:
                fail('conflict', f'文件在保存期间发生变化：{relative}。')
            os.replace(tmp, p)
            directory = os.open(p.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _put(self, table, key, data):
        with self.conn() as c:
            if table == 'reflection_versions':
                c.execute('INSERT INTO reflection_versions VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',
                          (key, encoded(data)))
            else:
                c.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                          (key, encoded(data)))

    # ---------- 校验 ----------
    def validate(self, data):
        date = data.get('record_date')
        if not isinstance(date, str) or not DATE.fullmatch(date):
            fail('invalid', '记录日期无效。', 422)
        kind = data.get('prompt_kind', '自由记录')
        if kind not in PROMPT_KINDS:
            fail('invalid', '思考方向无效。', 422)
        raw = data.get('raw_text', '')
        if not isinstance(raw, str) or not raw.strip():
            fail('invalid', '记录正文不能为空。', 422)
        if len(raw) > MAX_TEXT:
            fail('invalid', '记录正文过长，请精简。', 422)
        answers = data.get('guided_answers')
        if answers is None:
            answers = {}
        if not isinstance(answers, dict):
            fail('invalid', '深入回答格式无效。', 422)

    # ---------- 公开方法 ----------
    def list_entries(self, include_archived=False):
        rows = self.rows('reflection_entries')
        if not include_archived:
            rows = [r for r in rows if not r.get('archived_at')]
        rows.sort(key=lambda r: (r.get('record_date', ''), r.get('created_at', '')), reverse=True)
        return rows

    def entry(self, entry_id):
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        return self.get('reflection_entries', entry_id)

    def create(self, data, key):
        self.validate(data)
        request = {'op': 'create', **data}
        with self.lock():
            self.recover_locked()
            replay = self.replay(key, request)
            if replay is not None:
                return replay
            entry_id = 'ref-' + uuid.uuid4().hex
            record_date = data['record_date']
            entry = {
                'id': entry_id, 'record_date': record_date,
                'prompt_kind': data.get('prompt_kind', '自由记录'),
                'raw_text': data['raw_text'].strip(),
                'guided_answers': data.get('guided_answers') or {},
                'tags': data.get('tags') or [],
                'adopted_summary': None, 'summary_basis_version': None,
                'archived_at': None, 'created_at': now(), 'updated_at': now(),
                'version': 1, 'path': entry_path(entry_id, record_date),
                'status': 'recorded',
            }
            rel = entry['path'][len(REFLECTION_DIR) + 1:] if entry['path'].startswith(REFLECTION_DIR + '/') else entry['path']
            md = render_markdown(entry)
            entry['mirror_hash'] = digest(md)
            files = {entry['path']: {'old': None, 'content': md, 'new': digest(md)}}
            version = {'entry_id': entry_id, 'version': 1, 'record_date': record_date,
                       'prompt_kind': entry['prompt_kind'], 'raw_text': entry['raw_text'],
                       'guided_answers': entry['guided_answers'], 'tags': entry['tags'],
                       'adopted_summary': None,
                       'created_at': entry['created_at']}
            records = [
                {'sql': 'INSERT INTO reflection_entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                 'params': [entry_id, encoded(entry)]},
                {'sql': 'INSERT INTO reflection_versions VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',
                 'params': [f'{entry_id}#1', encoded(version)]},
            ]
            return self.publish(key, request, files, records, {'id': entry_id, 'version': 1})

    def update(self, entry_id, data, key):
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        base_version = data.get('base_version')
        if not isinstance(base_version, int) or base_version < 1:
            fail('invalid', '缺少基础版本。', 422)
        self.validate(data)
        request = {'op': 'update', 'entry_id': entry_id, **data}
        with self.lock():
            self.recover_locked()
            replay = self.replay(key, request)
            if replay is not None:
                return replay
            entry = self.get('reflection_entries', entry_id)
            if entry.get('archived_at'):
                fail('conflict', '已归档记录不能直接修改。')
            if entry['version'] != base_version:
                fail('conflict', '记录已被更新，请重新查看。')
            expected_hash = self.expected_mirror(entry)
            new_version = entry['version'] + 1
            entry.update(
                record_date=data['record_date'],
                prompt_kind=data.get('prompt_kind', '自由记录'),
                raw_text=data['raw_text'].strip(),
                guided_answers=data.get('guided_answers') or {},
                tags=data.get('tags') or [],
                updated_at=now(), version=new_version)
            # 采用整理后若原文变更，标记依据过期。
            if entry.get('adopted_summary') and entry['summary_basis_version'] is not None:
                entry['status'] = 'basis_updated'
            md = render_markdown(entry)
            entry['mirror_hash'] = digest(md)
            files = {entry['path']: {'old': expected_hash, 'content': md, 'new': digest(md)}}
            version = {'entry_id': entry_id, 'version': new_version, 'record_date': entry['record_date'],
                       'prompt_kind': entry['prompt_kind'], 'raw_text': entry['raw_text'],
                       'guided_answers': entry['guided_answers'], 'tags': entry['tags'],
                       'adopted_summary': entry['adopted_summary'],
                       'created_at': now()}
            records = [
                {'sql': 'INSERT INTO reflection_entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                 'params': [entry_id, encoded(entry)]},
                {'sql': 'INSERT INTO reflection_versions VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data',
                 'params': [f'{entry_id}#{new_version}', encoded(version)]},
            ]
            return self.publish(key, request, files, records, {'id': entry_id, 'version': new_version})

    def versions(self, entry_id):
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        self.entry(entry_id)
        with self.conn() as c:
            rows = c.execute("SELECT data FROM reflection_versions WHERE key LIKE ? ORDER BY key",
                             (f'{entry_id}#%',)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def adopt(self, entry_id, attempt_key, key):
        """采用 AI 整理：原文版本未变才可写入，原话永不覆盖。"""
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        request = {'op': 'adopt', 'entry_id': entry_id, 'attempt_key': attempt_key}
        with self.lock():
            self.recover_locked()
            replay = self.replay(key, request)
            if replay is not None:
                return replay
            entry = self.get('reflection_entries', entry_id)
            if entry.get('archived_at'):
                fail('conflict', '已归档记录不能修改。')
            with self.conn() as c:
                row = c.execute('SELECT data FROM reflection_ai_attempts WHERE id=?', (attempt_key,)).fetchone()
            if not row:
                fail('not_found', 'AI 建议不存在。', 404)
            attempt = json.loads(row[0])
            if attempt['kind'] != 'organize' or attempt['status'] != 'ready':
                fail('conflict', '整理尚未就绪，不能采用。')
            if attempt.get('version_at_request') != entry['version']:
                fail('conflict', '原文已变化，需要重新整理。')
            sections = attempt.get('sections') or []
            if not sections:
                fail('invalid', '整理内容为空。', 422)
            expected_hash = self.expected_mirror(entry)
            new_version = entry['version'] + 1
            entry.update(
                adopted_summary={'sections': sections, 'adopted_at': now()},
                summary_basis_version=entry['version'],
                status='organized', version=new_version, updated_at=now())
            md = render_markdown(entry)
            entry['mirror_hash'] = digest(md)
            files = {entry['path']: {'old': expected_hash, 'content': md, 'new': digest(md)}}
            records = [{'sql': 'INSERT INTO reflection_entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        'params': [entry_id, encoded(entry)]}]
            return self.publish(key, request, files, records, {'id': entry_id, 'version': new_version})

    def archive(self, entry_id, key):
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        request = {'op': 'archive', 'entry_id': entry_id}
        with self.lock():
            self.recover_locked()
            replay = self.replay(key, request)
            if replay is not None:
                return replay
            entry = self.get('reflection_entries', entry_id)
            if entry.get('archived_at'):
                return {'id': entry_id, 'archived': True}
            expected_hash = self.expected_mirror(entry)
            entry['archived_at'] = now()
            entry['updated_at'] = now()
            entry['version'] += 1
            md = render_markdown(entry)
            entry['mirror_hash'] = digest(md)
            files = {entry['path']: {'old': expected_hash, 'content': md, 'new': digest(md)}}
            records = [{'sql': 'INSERT INTO reflection_entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        'params': [entry_id, encoded(entry)]}]
            return self.publish(key, request, files, records, {'id': entry_id, 'archived': True})

    def restore(self, entry_id, key):
        if not ID.fullmatch(entry_id):
            fail('not_found', '记录不存在。', 404)
        request = {'op': 'restore', 'entry_id': entry_id}
        with self.lock():
            self.recover_locked()
            replay = self.replay(key, request)
            if replay is not None:
                return replay
            entry = self.get('reflection_entries', entry_id)
            if not entry.get('archived_at'):
                return {'id': entry_id, 'archived': False}
            expected_hash = self.expected_mirror(entry)
            entry['archived_at'] = None
            entry['updated_at'] = now()
            entry['version'] += 1
            md = render_markdown(entry)
            entry['mirror_hash'] = digest(md)
            files = {entry['path']: {'old': expected_hash, 'content': md, 'new': digest(md)}}
            records = [{'sql': 'INSERT INTO reflection_entries VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        'params': [entry_id, encoded(entry)]}]
            return self.publish(key, request, files, records, {'id': entry_id, 'archived': False})
