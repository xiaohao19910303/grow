"""Local course discovery and recoverable Markdown writes. No network dependencies."""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

MODULE = '每日认知与通识学习'
TZ = ZoneInfo('Asia/Shanghai')
NAME = re.compile(r'^(?:(\d{4}-\d{2}-\d{2})-)?第(\d+)课(?:-(.+))?\.md$')
ROW = re.compile(r'^\|\s*(\d+)\s*\|')
LINK = re.compile(r'\[[^\]]*\]\(([^)]+)\)')


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Problem(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def fail(code, message, status=409):
    raise Problem(code, message, status)


def kind(number):
    return '整合复盘' if number % 28 == 0 else '周复盘' if number % 7 == 0 else '普通课'


def structure_errors(text, number):
    groups = [('引导问题', ('引导问题',)), ('概念', ('概念', '解释', '知识回顾')),
              ('示范', ('示范', '案例')), ('边界', ('边界', '误区')),
              ('练习', ('练习',)), ('参考分析', ('参考分析',)),
              ('自查', ('自查',)), ('记忆提示', ('记忆提示',))]
    if number % 7 == 0:
        groups += [('复盘', ('复盘', '回顾'))]
    if number % 28 == 0:
        groups += [('整合', ('整合', '跨领域'))]
    errors = [f'缺少{name}' for name, words in groups if not any(w in text for w in words)]
    match = re.search(r'^#\s*第0*(\d+)课', text, re.M)
    if not match or int(match[1]) != number:
        errors.append('标题课次不匹配')
    if not re.search(r'日期[：:]\s*\d{4}-\d{2}-\d{2}', text):
        errors.append('缺少正文日期')
    return errors


class Store:
    def __init__(self, root, db):
        self.root = Path(root).absolute()
        self.db = Path(db)
        self.module = self.root / MODULE
        self.runtime = self.db.parent / '.copilot'

    @contextmanager
    def conn(self):
        connection = sqlite3.connect(self.db, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def workspace(self):
        try:
            for name in ('学习规划.md', '学习记录.md'):
                self.path(name).read_text(encoding='utf-8')
            if not self.path('每日课程').is_dir() or not self.path('参考资料').is_dir():
                raise OSError('missing course folders')
        except (OSError, UnicodeError):
            fail('workspace_unavailable', '学习目录不可访问，请检查挂载卷、目录和读取权限。', 503)

    def path(self, relative):
        p = self.module / relative
        # Reject symlinks even when they point inside: the target can be swapped later.
        for part in [p, *p.parents]:
            if part.is_symlink():
                fail('conflict', '课程路径不能经过符号链接。')
            if part == self.root:
                break
        if not p.resolve().is_relative_to(self.module.resolve()):
            fail('conflict', '路径超出课程目录。')
        return p

    @contextmanager
    def lock(self):
        self.workspace()
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / 'renzhi.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def initialize(self):
        self.workspace()
        if (self.runtime / 'restore-pending.json').exists():
            fail('save_pending_recovery', '存在未完成的离线恢复，请先处理恢复日志。', 503)
        with self.lock():
            with self.conn() as c:
                installed = c.execute("SELECT 1 FROM sqlite_master WHERE name='copilot_meta'").fetchone()
            if not installed:
                # SQLite backup API captures a consistent database; never copy a live db file.
                from .backup import snapshot
                snapshot(self, 'before-migration')
            with self.conn() as c:
                c.executescript('''
                CREATE TABLE IF NOT EXISTS copilot_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copilot_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copilot_lessons (
                    module_id TEXT NOT NULL DEFAULT 'renzhi', round_id INTEGER NOT NULL DEFAULT 1,
                    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
                    data TEXT NOT NULL, PRIMARY KEY(module_id,round_id,lesson_no));
                CREATE TABLE IF NOT EXISTS copilot_drafts (
                    id TEXT PRIMARY KEY, lesson_no INTEGER NOT NULL, version INTEGER NOT NULL,
                    status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copilot_generation_attempts (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
                    draft_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copilot_operations (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
                    status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS copilot_learning_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module_id TEXT NOT NULL DEFAULT 'renzhi',
                    round_id INTEGER NOT NULL DEFAULT 1,
                    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
                    completion_type TEXT NOT NULL CHECK(completion_type IN ('review', 'summary', 'quick', 'manual')),
                    review_answers TEXT,
                    summary_text TEXT,
                    time_spent_seconds INTEGER,
                    scroll_depth REAL,
                    completed_at TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    UNIQUE(module_id, round_id, lesson_no));
                ''')
                c.execute("INSERT INTO copilot_meta VALUES('schema_version','1') ON CONFLICT(key) DO NOTHING")
                schema_ver = c.execute("SELECT value FROM copilot_meta WHERE key='schema_version'").fetchone()[0]
                if schema_ver < '2':
                    c.execute("DROP TABLE IF EXISTS copilot_learning_records")
                    c.execute('''CREATE TABLE copilot_learning_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        module_id TEXT NOT NULL DEFAULT 'renzhi',
                        round_id INTEGER NOT NULL DEFAULT 1,
                        lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
                        completion_type TEXT NOT NULL CHECK(completion_type IN ('review', 'summary', 'quick', 'manual')),
                        review_answers TEXT,
                        summary_text TEXT,
                        time_spent_seconds INTEGER,
                        scroll_depth REAL,
                        completed_at TEXT NOT NULL,
                        idempotency_key TEXT UNIQUE,
                        UNIQUE(module_id, round_id, lesson_no))''')
                    c.execute("UPDATE copilot_meta SET value='2' WHERE key='schema_version'")
                # A stopped process must not leave drafts permanently 'generating'.
                c.execute("UPDATE copilot_drafts SET status='failed' WHERE status='generating'")
                c.execute("UPDATE copilot_generation_attempts SET status='failed' WHERE status='generating'")
            self.set_meta('writer_session', {})
            self._scan()

    def rows(self, text):
        return [(i, int(m[1]), line) for i, line in enumerate(text.splitlines(keepends=True))
                if (m := ROW.match(line))]

    def record_rows(self, text):
        # Personal notes can contain their own numbered tables; they are not course entries.
        catalog = text.split('## 个人记录区', 1)[0]
        return self.rows(catalog)

    def _scan(self):
        self.workspace()
        record = self.path('学习记录.md').read_text(encoding='utf-8')
        rows = self.record_rows(record)
        grouped, blockers, courses = {}, [], []
        for p in sorted(self.path('每日课程').glob('*.md')):
            m = NAME.fullmatch(p.name)
            if not m:
                blockers.append({'code': 'course_incomplete', 'message': f'未识别文件名：{p.name}'})
                continue
            n = int(m[2])
            if not 1 <= n <= 168:
                blockers.append({'code': 'course_incomplete', 'message': f'课次超出第一轮范围：{p.name}'})
                continue
            grouped.setdefault(n, []).append((p, m))
        for n, entries in sorted(grouped.items()):
            errors = []
            if len(entries) != 1:
                errors.append('同课多个文件：' + '、'.join(p.name for p, _ in entries))
            p, match = entries[0]
            relative = str(p.relative_to(self.module))
            text = self.path(relative).read_text(encoding='utf-8')
            errors += structure_errors(text, n)
            body_date = re.search(r'日期[：:]\s*(\d{4}-\d{2}-\d{2})', text)
            date_s = match[1] or (body_date[1] if body_date else '')
            try:
                datetime.strptime(date_s, '%Y-%m-%d')
            except ValueError:
                errors.append('日期缺失或无效')
            if match[1] and body_date and match[1] != body_date[1]:
                errors.append('文件名与正文日期不一致')
            source_path = f'参考资料/第{n:03d}课-参考资料.md'
            source = self.path(source_path)
            sources = source.read_text(encoding='utf-8') if source.exists() else ''
            if not sources.strip():
                errors.append('参考资料缺失或为空')
            matched = [line for _, no, line in rows if no == n]
            if len(matched) != 1:
                errors.append('学习记录缺失或重复')
            else:
                links = [unquote(link.split('#')[0]) for link in LINK.findall(matched[0])]
                if relative not in links or source_path not in links:
                    errors.append('学习记录链接不匹配')
            for parent, content in ((p.parent, text), (source.parent, sources)):
                for link in LINK.findall(content):
                    if urlparse(link).scheme or link.startswith('#'):
                        continue
                    target = (parent / unquote(link.split('#')[0])).resolve()
                    if not target.is_relative_to(self.module.resolve()) or not target.is_file():
                        errors.append('本地链接缺失或越界')
            status = matched[0].strip().strip('|').split('|')[-1].strip() if len(matched) == 1 else ''
            completed = status.startswith('已完成') or status.startswith('已学习')
            title = re.search(r'^#\s*第\d+课[：:]\s*(.+)$', text, re.M)
            lesson = {'lesson_no': n, 'topic': title[1] if title else match[3] or p.stem,
                      'date': date_s, 'path': relative, 'source_path': source_path,
                      'content_hash': digest(text), 'source_hash': digest(sources),
                      'version': digest(text + sources + record), 'complete': not errors,
                      'learning_state': 'completed' if completed else 'unknown',
                      'learning_label': status or '待本人记录', 'errors': errors}
            # Also check database for completion records
            with self.conn() as c:
                db_record = c.execute('''
                    SELECT completed_at, time_spent_seconds FROM copilot_learning_records
                    WHERE module_id = 'renzhi' AND round_id = 1 AND lesson_no = ?
                ''', (n,)).fetchone()
                if db_record:
                    lesson['learning_state'] = 'completed'
                    lesson['completed_at'] = db_record['completed_at']
                    lesson['time_spent_seconds'] = db_record['time_spent_seconds']
                    if not status:
                        lesson['learning_label'] = '已学习'
            courses.append(lesson)
        counts = Counter(x['date'] for x in courses if x['date'])
        for x in courses:
            if counts[x['date']] > 1:
                x['errors'].append('同日存在多课，请先处理')
                x['complete'] = False
            if x['errors']:
                blockers.append({'code': 'course_incomplete', 'lesson_no': x['lesson_no'],
                                 'message': '；'.join(x['errors'])})
        for n in range(1, max(grouped, default=0) + 1):
            if n not in grouped:
                blockers.append({'code': 'course_incomplete', 'lesson_no': n, 'message': f'缺少第{n:03d}课'})
        complete = {x['lesson_no'] for x in courses if x['complete']}
        prefix = 0
        while prefix + 1 in complete:
            prefix += 1
        with self.conn() as c:
            c.execute('DELETE FROM copilot_lessons')
            c.executemany('INSERT INTO copilot_lessons(lesson_no,data) VALUES (?,?)',
                          [(x['lesson_no'], encoded(x)) for x in courses])
            pending = c.execute("SELECT id FROM copilot_operations WHERE status!='done'").fetchall()
        blockers.extend({'code': 'save_pending_recovery', 'message': '保存操作需要恢复', 'operation_id': r[0]}
                        for r in pending)
        return {'lessons': courses, 'generated_count': len(complete),
                'completed_count': sum(x['learning_state'] == 'completed' for x in courses),
                'total_lessons': 168, 'next_generation_lesson': prefix + 1 if prefix < 168 else None,
                'pending_learning_lessons': [x for x in courses if x['learning_state'] != 'completed'],
                'today_lessons': [x for x in courses if x['date'] == now()[:10]], 'blockers': blockers}

    def scan(self):
        with self.lock():
            return self._scan()

    def lesson(self, number):
        data = self.scan()
        found = next((x for x in data['lessons'] if x['lesson_no'] == number), None)
        if not found:
            fail('not_found', '未找到课程。', 404)
        return {**found, 'content': self.path(found['path']).read_text(encoding='utf-8'),
                'sources': self.path(found['source_path']).read_text(encoding='utf-8')
                if self.path(found['source_path']).exists() else ''}

    def meta(self, key, default=None):
        with self.conn() as c:
            row = c.execute('SELECT value FROM copilot_meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.conn() as c:
            c.execute('INSERT INTO copilot_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (key, encoded(value)))

    def get_setting(self, key, default=''):
        with self.conn() as c:
            row = c.execute('SELECT value FROM copilot_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def update_settings(self, updates):
        with self.conn() as c:
            for key, value in updates.items():
                c.execute('INSERT INTO copilot_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                          (key, encoded(value)))

    def plan(self):
        self.workspace()
        p = self.path('课程主题规划.md')
        extended = p.exists()
        text = (p if extended else self.path('学习规划.md')).read_text(encoding='utf-8')
        h = digest(text)
        confirmations = self.meta('plan_confirmation', {})
        items = []
        for _, n, line in self.rows(text):
            if not 1 <= n <= 168:
                fail('plan_required', '主题规划含无效课次。')
            cells = [x.strip() for x in line.strip().strip('|').split('|')]
            items.append({'lesson_no': n, 'topic': cells[1], 'kind': kind(n),
                          'goal': cells[2] if extended and len(cells) > 2 else cells[1],
                          'confirmed': (not extended and n <= 7) or
                          (confirmations.get('hash') == h and n in confirmations.get('lessons', []))})
        if len({x['lesson_no'] for x in items}) != len(items):
            fail('plan_required', '主题规划中存在重复课次。')
        return {'hash': h, 'path': p.name if extended else '学习规划.md', 'items': items}

    def confirm_plan(self, expected, numbers):
        with self.lock():
            plan = self.plan()
            if plan['hash'] != expected or not set(numbers) <= {x['lesson_no'] for x in plan['items']}:
                fail('conflict', '规划已变化或课次无效，请重新查看。')
            previous = self.meta('plan_confirmation', {})
            old = previous.get('lessons', []) if previous.get('hash') == expected else []
            self.set_meta('plan_confirmation', {'hash': expected, 'lessons': sorted(set(old + numbers)), 'at': now()})
            return self.plan()

    def sources(self, number):
        """Structured manifest references a deliberately selected local teaching note."""
        p = self.path(f'备课资料/第{number:03d}课.json')
        if not p.is_file():
            fail('sources_required', f'请准备备课资料/第{number:03d}课.json及已核验的本地摘要。')
        try:
            entries = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(entries, list) or not entries:
                raise ValueError()
            result = []
            for item in entries:
                if not all(isinstance(item.get(k), str) and item[k].strip() for k in
                           ('title', 'url', 'verified_at', 'verification', 'claim', 'note_path')):
                    raise ValueError()
                if urlparse(item['url']).scheme not in ('https', 'http'):
                    raise ValueError()
                datetime.strptime(item['verified_at'], '%Y-%m-%d')
                note_path = item['note_path']
                if not note_path.startswith('备课资料/') or not note_path.endswith('.md'):
                    raise ValueError()
                note = self.path(note_path).read_text(encoding='utf-8')
                if not note.strip() or len(note) > 30000:
                    raise ValueError()
                result.append({**item, 'note': note})
            if len(result) > 8:
                raise ValueError()
            return {'entries': result, 'hash': digest(encoded(result))}
        except (ValueError, OSError, KeyError, TypeError):
            fail('sources_required', '资料清单格式不完整、日期/链接无效或本地摘要不可读取。')

    def readiness(self, data=None):
        data = data or self._scan()
        blockers = list(data['blockers'])
        n = data['next_generation_lesson']
        if n is None:
            blockers.append({'code': 'round_complete', 'message': '第一轮内容已生成完毕。'})
        if data['today_lessons']:
            blockers.append({'code': 'already_generated_today', 'message': '今天已有课程，请先阅读。'})
        plan, sources = None, None
        if n:
            try:
                mapping = self.plan()
                entry = next((x for x in mapping['items'] if x['lesson_no'] == n and x['confirmed']), None)
                if not entry:
                    fail('plan_required', f'第{n:03d}课主题尚未确认。')
                plan = {**entry, 'hash': mapping['hash']}
            except Problem as e:
                blockers.append({'code': e.code, 'message': e.message})
            try:
                sources = self.sources(n)
            except Problem as e:
                blockers.append({'code': e.code, 'message': e.message})
        return data, plan, sources, blockers

    def coordinated(self):
        session = self.meta('writer_session', {})
        return bool(session.get('expires_at', '') > now())

    def require_writer(self):
        if not self.coordinated():
            fail('external_writer_uncoordinated', '请先确认自动任务及其他编辑器在本次写入期间已暂停写入。')

    def writer_session(self, confirmed):
        if confirmed is not True:
            fail('external_writer_uncoordinated', '需要本人明确确认当前安全写入时段。')
        from datetime import timedelta
        with self.lock():
            value = {'confirmed_at': now(), 'expires_at': (datetime.now(TZ) + timedelta(minutes=10)).isoformat(timespec='seconds'),
                     'reason': '用户确认其他写入方在此时段暂停写入'}
            self.set_meta('writer_session', value)
        return value

    def file_hash(self, relative):
        p = self.path(relative)
        return digest(p.read_bytes()) if p.exists() else None

    def operation(self, op_id):
        with self.conn() as c:
            row = c.execute('SELECT * FROM copilot_operations WHERE id=?', (op_id,)).fetchone()
        if not row:
            fail('not_found', '保存操作不存在。', 404)
        return dict(row)

    def replay(self, key, request):
        with self.conn() as c:
            row = c.execute('SELECT * FROM copilot_operations WHERE request_key=?', (key,)).fetchone()
        if row:
            if row['request_hash'] != digest(encoded(request)):
                fail('conflict', '同一请求标识不能用于不同内容。')
            return {'operation_id': row['id'], 'status': row['status']}

    def prepare(self, key, request, files, draft_id=None):
        op_id = str(uuid.uuid4())
        # Store durable target content in the journal itself; filesystem staging is recreated as needed.
        data = {'files': files, 'draft_id': draft_id}
        with self.conn() as c:
            c.execute('INSERT INTO copilot_operations VALUES (?,?,?,?,?,?)',
                      (op_id, key, digest(encoded(request)), 'prepared', encoded(data), now()))
        return self._resume(op_id)

    def _resume(self, op_id):
        row = self.operation(op_id)
        if row['status'] == 'done':
            return {'operation_id': op_id, 'status': 'done'}
        data = json.loads(row['data'])
        try:
            # Preflight every target before touching any file.
            for item in data['files']:
                if self.file_hash(item['path']) not in (item['old_hash'], digest(item['content'])):
                    fail('conflict', '文件已被外部修改：' + item['path'])
            for item in data['files']:
                target_hash = digest(item['content'])
                if self.file_hash(item['path']) == target_hash:
                    continue
                p = self.path(item['path'])
                p.parent.mkdir(parents=True, exist_ok=True)
                fd, temp = tempfile.mkstemp(prefix='.copilot-', dir=p.parent)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        stream.write(item['content'])
                        stream.flush()
                        os.fsync(stream.fileno())
                    if self.file_hash(item['path']) != item['old_hash']:
                        fail('conflict', '文件在保存期间发生变化：' + item['path'])
                    if item['old_hash'] is None:
                        os.link(temp, p)  # Atomic create, never replace an existing course.
                    else:
                        os.replace(temp, p)
                    directory = os.open(p.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            self._scan()
            with self.conn() as c:
                if data.get('draft_id'):
                    c.execute("UPDATE copilot_drafts SET status='published' WHERE id=?", (data['draft_id'],))
                c.execute("UPDATE copilot_operations SET status='done' WHERE id=?", (op_id,))
            return {'operation_id': op_id, 'status': 'done'}
        except (OSError, sqlite3.Error, Problem) as e:
            data['error'] = e.message if isinstance(e, Problem) else '文件或数据库写入失败，检查磁盘与权限后恢复。'
            with self.conn() as c:
                c.execute("UPDATE copilot_operations SET status=?,data=? WHERE id=?",
                          ('conflict' if isinstance(e, Problem) else 'pending_recovery', encoded(data), op_id))
            fail('save_pending_recovery', f'操作{op_id}待恢复；文件变化时不会覆盖，请查看操作状态。')

    def recover(self, op_id):
        with self.lock():
            self.require_writer()
            return self._resume(op_id)

    def learning(self, number, state, version, key):
        request = {'lesson_no': number, 'state': state, 'version': version}
        with self.lock():
            previous = self.replay(key, request)
            if previous:
                return previous
            self.require_writer()
            data = self._scan()
            if any(b['code'] == 'save_pending_recovery' for b in data['blockers']):
                fail('save_pending_recovery', '请先恢复尚未完成的保存操作。')
            lesson = next((x for x in data['lessons'] if x['lesson_no'] == number), None)
            if not lesson:
                fail('not_found', '未找到课程。')
            if not lesson['complete']:
                fail('conflict', '课程记录不完整，请先生成完整课程再操作。')
            if lesson['version'] != version:
                fail('conflict', '课程已更新，请刷新页面后重试。')

            ts = now()
            text = self.path('学习记录.md').read_text(encoding='utf-8')
            lines = text.splitlines(keepends=True)
            matches = [(i, line) for i, n, line in self.record_rows(text) if n == number]
            if len(matches) != 1:
                fail('conflict', '无法唯一定位学习记录。')
            i, line = matches[0]
            cells = line.rstrip('\r\n').split('|')
            cells[-2] = f' 已完成（本人确认：{ts}） ' if state == 'completed' else f' 待本人记录（本人撤销：{ts}） '
            lines[i] = '|'.join(cells) + ('\n' if line.endswith('\n') else '')
            result = self.prepare(key, request, [{'path': '学习记录.md', 'old_hash': digest(text), 'content': ''.join(lines)}])

            if state == 'completed':
                with self.conn() as c:
                    c.execute('''
                        INSERT OR REPLACE INTO copilot_learning_records
                        (module_id, round_id, lesson_no, completion_type, time_spent_seconds,
                         completed_at, idempotency_key)
                        VALUES ('renzhi', 1, ?, 'manual', 0, ?, ?)
                    ''', (number, ts, key))
            elif state == 'unknown':
                with self.conn() as c:
                    c.execute('DELETE FROM copilot_learning_records WHERE module_id=? AND round_id=1 AND lesson_no=?',
                              ('renzhi', number))
            return result

    def submit_review(self, number, answers, time_spent, version, key):
        """Submit review answers and mark lesson as completed."""
        request = {'lesson_no': number, 'action': 'review', 'version': version}
        with self.lock():
            previous = self.replay(key, request)
            if previous:
                return previous
            self.require_writer()
            data = self._scan()
            if any(b['code'] == 'save_pending_recovery' for b in data['blockers']):
                fail('save_pending_recovery', '请先恢复尚未完成的保存操作。')
            lesson = next((x for x in data['lessons'] if x['lesson_no'] == number), None)
            if not lesson:
                fail('not_found', '未找到课程。')
            if not lesson['complete']:
                fail('conflict', '课程记录不完整，请先生成完整课程再操作。')
            if lesson['version'] != version:
                fail('conflict', '课程已更新，请刷新页面后重试。')

            text = self.path('学习记录.md').read_text(encoding='utf-8')
            lines = text.splitlines(keepends=True)
            matches = [(i, line) for i, n, line in self.record_rows(text) if n == number]
            if len(matches) != 1:
                fail('conflict', '无法唯一定位学习记录。')
            i, line = matches[0]
            cells = line.rstrip('\r\n').split('|')
            ts = now()
            cells[-2] = f' 已完成（复盘提交：{ts}） '
            lines[i] = '|'.join(cells) + ('\n' if line.endswith('\n') else '')
            result = self.prepare(key, request, [{'path': '学习记录.md', 'old_hash': digest(text), 'content': ''.join(lines)}])

            with self.conn() as c:
                c.execute('''
                    INSERT INTO copilot_learning_records
                    (module_id, round_id, lesson_no, completion_type, review_answers,
                     time_spent_seconds, completed_at, idempotency_key)
                    VALUES ('renzhi', 1, ?, 'review', ?, ?, ?, ?)
                ''', (number, json.dumps(answers, ensure_ascii=False), time_spent, ts, key))
            return result

    def submit_summary(self, number, summary, time_spent, version, key):
        """Submit learning summary and mark lesson as completed."""
        request = {'lesson_no': number, 'action': 'summary', 'version': version}
        with self.lock():
            previous = self.replay(key, request)
            if previous:
                return previous
            self.require_writer()
            data = self._scan()
            if any(b['code'] == 'save_pending_recovery' for b in data['blockers']):
                fail('save_pending_recovery', '请先恢复尚未完成的保存操作。')
            lesson = next((x for x in data['lessons'] if x['lesson_no'] == number), None)
            if not lesson:
                fail('not_found', '未找到课程。')
            if not lesson['complete']:
                fail('conflict', '课程记录不完整，请先生成完整课程再操作。')
            if lesson['version'] != version:
                fail('conflict', '课程已更新，请刷新页面后重试。')

            text = self.path('学习记录.md').read_text(encoding='utf-8')
            lines = text.splitlines(keepends=True)
            matches = [(i, line) for i, n, line in self.record_rows(text) if n == number]
            if len(matches) != 1:
                fail('conflict', '无法唯一定位学习记录。')
            i, line = matches[0]
            cells = line.rstrip('\r\n').split('|')
            ts = now()
            cells[-2] = f' 已完成（总结提交：{ts}） '
            lines[i] = '|'.join(cells) + ('\n' if line.endswith('\n') else '')
            result = self.prepare(key, request, [{'path': '学习记录.md', 'old_hash': digest(text), 'content': ''.join(lines)}])

            with self.conn() as c:
                c.execute('''
                    INSERT INTO copilot_learning_records
                    (module_id, round_id, lesson_no, completion_type, summary_text,
                     time_spent_seconds, completed_at, idempotency_key)
                    VALUES ('renzhi', 1, ?, 'summary', ?, ?, ?, ?)
                ''', (number, summary, time_spent, ts, key))
            return result

    def quick_complete(self, number, time_spent, version, key):
        """Quick mark lesson as completed without review or summary."""
        request = {'lesson_no': number, 'action': 'quick', 'version': version}
        with self.lock():
            previous = self.replay(key, request)
            if previous:
                return previous
            self.require_writer()
            data = self._scan()
            if any(b['code'] == 'save_pending_recovery' for b in data['blockers']):
                fail('save_pending_recovery', '请先恢复尚未完成的保存操作。')
            lesson = next((x for x in data['lessons'] if x['lesson_no'] == number), None)
            if not lesson:
                fail('not_found', '未找到课程。')
            if not lesson['complete']:
                fail('conflict', '课程记录不完整，请先生成完整课程再操作。')
            if lesson['version'] != version:
                fail('conflict', '课程已更新，请刷新页面后重试。')

            text = self.path('学习记录.md').read_text(encoding='utf-8')
            lines = text.splitlines(keepends=True)
            matches = [(i, line) for i, n, line in self.record_rows(text) if n == number]
            if len(matches) != 1:
                fail('conflict', '无法唯一定位学习记录。')
            i, line = matches[0]
            cells = line.rstrip('\r\n').split('|')
            ts = now()
            cells[-2] = f' 已完成（快速完成：{ts}） '
            lines[i] = '|'.join(cells) + ('\n' if line.endswith('\n') else '')
            result = self.prepare(key, request, [{'path': '学习记录.md', 'old_hash': digest(text), 'content': ''.join(lines)}])

            with self.conn() as c:
                c.execute('''
                    INSERT INTO copilot_learning_records
                    (module_id, round_id, lesson_no, completion_type, time_spent_seconds,
                     completed_at, idempotency_key)
                    VALUES ('renzhi', 1, ?, 'quick', ?, ?, ?)
                ''', (number, time_spent, ts, key))
            return result

    def get_learning_record(self, number):
        """Get learning record for a specific lesson."""
        with self.conn() as c:
            row = c.execute('''
                SELECT completion_type, review_answers, summary_text,
                       time_spent_seconds, completed_at
                FROM copilot_learning_records
                WHERE module_id = 'renzhi' AND round_id = 1 AND lesson_no = ?
            ''', (number,)).fetchone()
        if not row:
            return None
        record = dict(row)
        if record['review_answers']:
            record['review_answers'] = json.loads(record['review_answers'])
        return record

    def get_learning_history(self, offset, limit):
        """Get learning history with pagination."""
        with self.conn() as c:
            total = c.execute('''
                SELECT COUNT(*) FROM copilot_learning_records
                WHERE module_id = 'renzhi' AND round_id = 1
            ''').fetchone()[0]

            rows = c.execute('''
                SELECT lesson_no, completion_type, review_answers, summary_text,
                       time_spent_seconds, completed_at
                FROM copilot_learning_records
                WHERE module_id = 'renzhi' AND round_id = 1
                ORDER BY completed_at DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset)).fetchall()

        items = []
        for row in rows:
            record = dict(row)
            if record['review_answers']:
                record['review_answers'] = json.loads(record['review_answers'])
            items.append(record)

        return {'total': total, 'items': items}

    def get_learning_history_by_date(self, module_id, date):
        """Get learning records for a specific date."""
        with self.conn() as c:
            rows = c.execute('''
                SELECT lesson_no, completion_type, review_answers, summary_text,
                       time_spent_seconds, completed_at
                FROM copilot_learning_records
                WHERE module_id = ? AND DATE(completed_at) = ?
                ORDER BY completed_at DESC
            ''', (module_id, date)).fetchall()

        items = []
        for row in rows:
            record = dict(row)
            if record['review_answers']:
                record['review_answers'] = json.loads(record['review_answers'])
            items.append(record)

        return {'date': date, 'total': len(items), 'items': items}

    def get_learning_history_months(self, module_id, start_date, end_date):
        """Get learning records for a date range (for calendar view)."""
        with self.conn() as c:
            rows = c.execute('''
                SELECT DATE(completed_at) as date, COUNT(*) as count
                FROM copilot_learning_records
                WHERE module_id = ? AND completed_at >= ? AND completed_at < ?
                GROUP BY DATE(completed_at)
                ORDER BY date DESC
            ''', (module_id, start_date, end_date)).fetchall()

        return {r['date']: r['count'] for r in rows}

    def extract_review_questions(self, number):
        """Extract review questions from lesson content."""
        lesson = self.lesson(number)
        content = lesson.get('content', '')

        # Find the practice section (练习)
        practice_match = re.search(r'##\s*练习[^\n]*\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if not practice_match:
            return None

        practice_text = practice_match.group(1)

        # Extract numbered questions (1. 2. 3. etc.)
        questions = []
        for match in re.finditer(r'(?:^|\n)\s*(\d+)[.、]\s*([^\n]+)', practice_text):
            question_text = match.group(2).strip()
            if question_text and len(question_text) > 5:
                questions.append({
                    'question_id': len(questions) + 1,
                    'question_text': question_text
                })
            if len(questions) >= 3:
                break

        # If no numbered questions found, try to extract from bullet points
        if not questions:
            for match in re.finditer(r'(?:^|\n)\s*[-*]\s*([^\n]+)', practice_text):
                question_text = match.group(1).strip()
                if question_text and len(question_text) > 5:
                    questions.append({
                        'question_id': len(questions) + 1,
                        'question_text': question_text
                    })
                if len(questions) >= 2:
                    break

        # If still no questions, return default questions
        if not questions:
            questions = [
                {'question_id': 1, 'question_text': '本课的核心概念是什么？用自己的话解释。'},
                {'question_id': 2, 'question_text': '你能举一个生活中的例子吗？'}
            ]

        return questions[:2]  # Return at most 2 questions

    def draft(self, draft_id):
        with self.conn() as c:
            row = c.execute('SELECT * FROM copilot_drafts WHERE id=?', (draft_id,)).fetchone()
        if not row:
            fail('not_found', '草稿不存在。', 404)
        return {**json.loads(row['data']), 'id': row['id'], 'lesson_no': row['lesson_no'],
                'version': row['version'], 'status': row['status'], 'updated_at': row['updated_at']}

    def validate_draft(self, d):
        errors = structure_errors(d['content'], d['lesson_no'])
        if not d['sources'].strip():
            errors.append('缺少参考资料摘要')
        allowed = {x['url'] for x in d['source_snapshot']['entries']}
        urls = set(re.findall(r'https?://[^\s<>\)\]"\u3002\uff0c]+', d['content'] + '\n' + d['sources']))
        if not urls or not urls <= allowed:
            errors.append('引用为空或含未核验来源')
        if not re.search(r'\n---\s*\n', d['content']):
            errors.append('练习与参考分析之间缺少分隔线')
        # Generated notes may only reference verified web sources, no arbitrary local paths.
        if any(not urlparse(link).scheme and not link.startswith('#') for link in LINK.findall(d['content'] + d['sources'])):
            errors.append('草稿不能引用未登记的本地文件')
        return errors

    def edit_draft(self, draft_id, version, content, sources):
        with self.lock():
            d = self.draft(draft_id)
            if d['version'] != version or d['status'] in ('generating', 'published'):
                fail('conflict', '草稿版本已变化或当前不可编辑。')
            d.update(content=content, sources=sources)
            errors = self.validate_draft(d)
            d['errors'] = errors
            # A failed/cancelled stream cannot be promoted by editing partial output.
            status = 'ready' if d.get('stream_completed') and not errors else 'failed'
            with self.conn() as c:
                c.execute('UPDATE copilot_drafts SET data=?,version=version+1,status=?,updated_at=? WHERE id=?',
                          (encoded(d), status, now(), draft_id))
            return self.draft(draft_id)

    def publish(self, draft_id, version, key):
        request = {'draft_id': draft_id, 'version': version}
        with self.lock():
            replay = self.replay(key, request)
            if replay:
                return replay
            self.require_writer()
            d = self.draft(draft_id)
            if d['version'] != version or d['status'] != 'ready' or self.validate_draft(d):
                fail('conflict', '草稿版本已变化、生成未完成或校验未通过。')
            state, plan, sources, blockers = self.readiness()
            if blockers:
                fail(blockers[0]['code'], blockers[0]['message'])
            if (state['next_generation_lesson'] != d['lesson_no'] or plan['hash'] != d['plan_snapshot']['hash']
                    or sources['hash'] != d['source_snapshot']['hash']):
                fail('conflict', '课次、规划或资料已经变化，请重新生成。')
            if self.file_hash('学习记录.md') != d['record_hash']:
                fail('conflict', '学习记录已被外部修改，请重新生成以更新上下文。')
            n = d['lesson_no']
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f\[\]()]', '', plan['topic']).strip()[:70] or f'第{n:03d}课'
            date_s = now()[:10]
            course = f'每日课程/{date_s}-第{n:03d}课-{title}.md'
            source = f'参考资料/第{n:03d}课-参考资料.md'
            if self.file_hash(course) is not None or self.file_hash(source) is not None:
                fail('conflict', '正式课程或资料已存在，不能覆盖。')
            content = re.sub(r'(日期[：:]\s*)\d{4}-\d{2}-\d{2}', r'\g<1>' + date_s, d['content'], count=1)
            content += f'\n\n资料：[第{n:03d}课参考资料](../{source})\n'
            source_text = f'# 第{n:03d}课参考资料\n\n对应课程：[{title}](../{course})\n\n' + d['sources']
            record = self.path('学习记录.md').read_text(encoding='utf-8')
            rows = self.record_rows(record)
            if any(num == n for _, num, _ in rows):
                fail('conflict', '记录中已存在该课。')
            lines = record.splitlines(keepends=True)
            position = max((i for i, _, _ in rows), default=-1) + 1
            if not rows:
                position = next((i + 1 for i, line in enumerate(lines) if line.startswith('|---')), -1)
            if position < 0:
                fail('conflict', '学习记录表格格式无法识别。')
            lines.insert(position, f'| {n:03d} | {date_s} | [{title}]({course}) | [参考资料]({source}) | 待本人记录 |\n')
            return self.prepare(key, request, [
                {'path': course, 'old_hash': None, 'content': content},
                {'path': source, 'old_hash': None, 'content': source_text},
                {'path': '学习记录.md', 'old_hash': digest(record), 'content': ''.join(lines)}], draft_id)
