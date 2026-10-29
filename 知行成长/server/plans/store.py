"""Plan identities, validated documents and recoverable local publications."""
import copy
import fcntl
import json
import os
import re
import sqlite3
import db
import tempfile
import uuid
from contextlib import contextmanager, closing
from pathlib import Path
from urllib.parse import urlparse

from copilot.core import digest, encoded, fail, now
from .refinement import content_hash, payload, sections, differences

PLAN_ID = re.compile(r'^plan-\d{8}-\d{3,}$')
LEGACY = [{'id': 'renzhi', 'name': '认知与通识', 'path': '每日认知与通识学习'},
          {'id': 'yingyu', 'name': '英文阅读', 'path': '英文阅读'},
          {'id': 'biaoda', 'name': '结构化表达', 'path': '结构化表达'}]
TABLES = '''
CREATE TABLE IF NOT EXISTS learning_plans (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    reason TEXT,
    FOREIGN KEY (plan_id) REFERENCES learning_plans(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_plan_status_plan_id ON plan_status_history(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_status_changed_at ON plan_status_history(changed_at);
CREATE TABLE IF NOT EXISTS learning_action_links (id TEXT PRIMARY KEY REFERENCES learning_plans(id), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_plan_versions (plan_id TEXT, version INTEGER, data TEXT NOT NULL, PRIMARY KEY(plan_id,version));
CREATE TABLE IF NOT EXISTS learning_lessons (plan_id TEXT, lesson_no INTEGER, data TEXT NOT NULL, PRIMARY KEY(plan_id,lesson_no));
CREATE TABLE IF NOT EXISTS learning_drafts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_ai_attempts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_feedback (plan_id TEXT, lesson_no INTEGER, data TEXT NOT NULL, PRIMARY KEY(plan_id,lesson_no));
CREATE TABLE IF NOT EXISTS learning_publications (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_draft_families (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_settings (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL REFERENCES learning_plans(id) ON DELETE CASCADE,
    from_status TEXT, to_status TEXT NOT NULL, changed_at TEXT NOT NULL, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_status_plan_id ON plan_status_history(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_status_changed_at ON plan_status_history(changed_at);
'''


def text(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        fail('invalid', f'{label}不能为空且不得超长。', 422)
    return value.strip()


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        fail('invalid', f'{label}须在{low}–{high}范围内。', 422)
    return value


def brief(data):
    if not isinstance(data, dict):
        fail('invalid', '学习条件格式不正确。', 422)
    base={k:text(data.get(k),label) for k,label in [('title','名称'),('goal','目的'),('level','基础')]}
    base['minutes']=integer(data.get('minutes'),5,120,'每次分钟数')
    pacing=data.get('pacing','weekly')
    if pacing=='self_paced':
        return {**base,'pacing':pacing,'lesson_count':integer(data.get('lesson_count'),2,364,'总课数')}
    if pacing!='weekly':fail('invalid','学习节奏无效。',422)
    return {**base,'weeks':integer(data.get('weeks'),1,52,'周数'),'sessions':integer(data.get('sessions'),1,7,'每周次数')}


def lesson_count(conditions):
    return conditions['lesson_count'] if conditions.get('pacing')=='self_paced' else conditions['weeks']*conditions['sessions']



def document(data, conditions):
    if not isinstance(data, dict):
        fail('invalid', '规划须为完整对象。', 422)
    result = {'prerequisites': text(data.get('prerequisites'), '先修说明'), 'stages': [], 'lessons': []}
    stages = data.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= (lesson_count(conditions) if conditions.get('pacing')=='self_paced' else conditions['weeks']):
        fail('invalid', '需要阶段目标，阶段数不能超过周数。', 422)
    for stage in stages:
        if not isinstance(stage, dict): fail('invalid', '阶段格式错误。', 422)
        result['stages'].append({k: text(stage.get(k), k) for k in ('title', 'goal')})
    lessons = data.get('lessons')
    if not isinstance(lessons, list) or len(lessons) != lesson_count(conditions):
        fail('invalid', '课次数量须与规划总课数一致，复盘包含在内。', 422)
    for n, lesson in enumerate(lessons, 1):
        if not isinstance(lesson, dict) or type(lesson.get('number')) is not int or lesson['number'] != n:
            fail('invalid', '课号须从1开始连续且唯一。', 422)
        row = {k: text(lesson.get(k), k, 1000) for k in ('topic', 'goal', 'exercise', 'assessment')}
        row['number'] = n
        row['minutes'] = integer(lesson.get('minutes'), 5, conditions['minutes'], '课时分钟数')
        row['stage'] = integer(lesson.get('stage'), 1, len(stages), '所属阶段')
        if lesson.get('kind') not in ('lesson', 'review'):
            fail('invalid', '课型须为lesson或review。', 422)
        row['kind'] = lesson['kind']
        requires = lesson.get('requires', [])
        if not isinstance(requires, list) or any(type(x) is not int or not 1 <= x < n for x in requires):
            fail('invalid', '先修课号必须指向之前的课。', 422)
        row['requires'] = sorted(set(requires))
        result['lessons'].append(row)
    if not any(x['kind'] == 'review' for x in result['lessons']):
        fail('invalid', '规划至少包含一次复盘。', 422)
    if conditions.get('pacing')=='self_paced' and result['lessons'][-1]['kind']!='review':
        fail('invalid','自由节奏规划最后一课须包含综合练习与复盘。',422)
    return result


def sources(entries):
    if not isinstance(entries, list) or not 1 <= len(entries) <= 10:
        fail('invalid', '请准备1–10份参考资料。', 422)
    result = []
    for item in entries:
        if not isinstance(item, dict): fail('invalid', '资料格式错误。', 422)
        title = text(item.get('title'), '标题', 4000)
        content = text(item.get('content'), '内容', 15000)
        if not title or not content:
            fail('invalid', '每份资料需要标题和内容。', 422)
        result.append({'title': title, 'content': content})
    if len(encoded(result)) > 80000: fail('invalid', '资料总量过长，请精简。', 422)
    return result


def plan_markdown(b, doc):
    schedule=(f'自由节奏：共{b["lesson_count"]}课，每次{b["minutes"]}分钟，不指定学习日期。' if b.get('pacing')=='self_paced' else f'安排：{b["weeks"]}周，每周{b["sessions"]}次，每次{b["minutes"]}分钟。')
    lines = [f'# {b["title"]}', '', f'学习目的：{b["goal"]}', f'当前基础：{b["level"]}',
             schedule,
             '', '## 先修说明', doc['prerequisites'], '', '## 阶段目标']
    for i, stage in enumerate(doc['stages'], 1):
        lines += [f'### 阶段{i}：{stage["title"]}', stage['goal']]
    for row in doc['lessons']:
        lines += ['', f'## 第{row["number"]:03d}课：{row["topic"]}',
                  f'阶段：{row["stage"]}｜类型：{row["kind"]}｜{row["minutes"]}分钟',
                  f'目标：{row["goal"]}', f'练习：{row["exercise"]}', f'自查：{row["assessment"]}',
                  f'先修课号：{row["requires"]}']
    return '\n'.join(lines) + '\n'


class Plans:
    def __init__(self, root, db):
        self.root, self.db = Path(root).absolute(), Path(db)
        self.runtime = self.db / '.plans'
        self.startup_error = None

    @contextmanager
    def conn(self):
        with closing(db.connect()) as c:
            with c: yield c

    @contextmanager
    def lock(self):
        if not self.root.is_dir(): fail('unavailable', '学习磁盘不可用。', 503)
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / 'write.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(stream, fcntl.LOCK_UN)

    def path(self, relative):
        p = self.root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            fail('invalid', '文件路径无效。', 422)
        if not relative.startswith('学习计划/'):
            fail('invalid', '路径不属于新学习计划。', 422)
        for part in (p, *p.parents):
            if part.is_symlink(): fail('conflict', '内容路径不能经过符号链接。')
            if part == self.root: break
        if not p.resolve().is_relative_to(self.root.resolve()): fail('conflict', '路径越界。')
        return p

    def base(self, pid):
        if not isinstance(pid, str) or not PLAN_ID.fullmatch(pid): fail('not_found', '学习计划不存在。', 404)
        return f'学习计划/{pid}'

    def hash(self, relative):
        p = self.path(relative)
        return digest(p.read_bytes()) if p.exists() else None

    def read_text(self, relative, ref=None):
        try:
            return self.path(relative).read_text(encoding='utf-8')
        except FileNotFoundError:
            fail('not_found', '课程资料文件缺失，请核对内容存储配置或恢复原文件后重试。', 404)

    def exists(self, relative):
        return self.path(relative).exists()

    def file_location(self, relative):
        return str(self.path(relative))

    def read_course(self, pid, number):
        self.plan(pid)
        lesson = next((x for x in self.lessons(pid) if x['lesson_no'] == number), None)
        if not lesson: fail('not_found', '课程不存在。', 404)
        if lesson.get('storage') == 'github':
            fail('content_backend', '这节课程保存在 GitHub，请启用 GitHub 内容存储后重试。', 503)
        base = self.base(pid)
        return {'lesson': lesson, 'content': self.read_text(base+'/'+lesson['path']),
                'sources': self.read_text(base+'/'+lesson['source'])}

    def initialize(self):
        if (self.runtime / 'restore-pending.json').exists():
            fail('restore_pending', '存在未完成的恢复，请先核对日志。', 503)
        with self.lock():
            with self.conn() as c:
                sqlite = isinstance(c, sqlite3.Connection)
                installed = c.execute("SELECT 1 FROM sqlite_master WHERE name='learning_draft_families'" if sqlite else
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='learning_draft_families'").fetchone()
            if not installed and sqlite:
                target = self.runtime / f'before-migration-{uuid.uuid4().hex}.db'
                from .backup import database_snapshot
                database_snapshot(self, target)
            with self.conn() as c: c.executescript(TABLES)
            with self.conn() as c:
                for row in c.execute('SELECT id,data FROM learning_ai_attempts').fetchall():
                    a = json.loads(row['data'])
                    if a['state'] in ('queued', 'generating'):
                        a.update(state='failed', error='服务已重启，生成中断；不会自动重试。')
                        c.execute('UPDATE learning_ai_attempts SET data=? WHERE id=?', (encoded(a), row['id']))
            self.recover_locked()
            self.migrate_draft_families()

    def migrate_draft_families(self):
        # Old drafts become independent roots; do not infer historical parentage.
        with self.conn() as c:
            drafts=[]
            for row in c.execute('SELECT id,data FROM learning_drafts').fetchall():
                try:d=json.loads(row[1])
                except (ValueError,TypeError):fail('draft_migration','旧草稿格式无法识别，原文保留，请先核对。',503)
                if not isinstance(d,dict) or d.get('id')!=row[0] or not isinstance(d.get('state'),str):
                    fail('draft_migration','旧草稿缺少编号或状态，原文保留，请先核对。',503)
                if d.get('family_id') is not None and not isinstance(d['family_id'],str):
                    fail('draft_migration','旧草稿族编号无效，原文保留，请先核对。',503)
                if not d.get('family_id') and d.get('parent_draft_id'):
                    fail('draft_migration','旧草稿已有父子关系但缺少族编号，原关系保留，请先核对。',503)
                drafts.append(d)
            families={row[0] for row in c.execute('SELECT id FROM learning_draft_families')}
            for d in drafts:
                if not d.get('family_id'):
                    d['family_id']=d['id'];d.setdefault('parent_draft_id',None);d.setdefault('operation','original')
                    c.execute('UPDATE learning_drafts SET data=? WHERE id=?',(encoded(d),d['id']))
            for d in drafts:
                if d['family_id']==d['id'] and d['id'] not in families:
                    published=[item['id'] for item in drafts if item['family_id']==d['id'] and item['state']=='published']
                    if len(published)>1:fail('draft_migration','旧草稿族存在多个已发布版本，原记录保留，请先核对。',503)
                    family={'id':d['id'],'published_draft_id':published[0] if published else None}
                    c.execute('INSERT INTO learning_draft_families VALUES (?,?)',(d['id'],encoded(family)))
                    families.add(d['id'])
            if any(d['family_id'] not in families for d in drafts):
                fail('draft_migration','旧草稿族缺少原始根草稿，原关系保留，请先核对。',503)

    def get(self, table, key):
        with self.conn() as c:
            row = c.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        if not row: fail('not_found', '记录不存在。', 404)
        return json.loads(row['data'])

    def get_setting(self, key, default=''):
        # Share the existing settings screen without creating a second credential store.
        with self.conn() as c:
            if isinstance(c, sqlite3.Connection):
                columns = {r[1] for r in c.execute('PRAGMA table_info(copilot_settings)')}
            else:
                columns = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='copilot_settings'")}
            if not {'key', 'value'} <= columns:
                return default
            row = c.execute('SELECT value FROM copilot_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def rows(self, table):
        with self.conn() as c: return [json.loads(r[0]) for r in c.execute(f'SELECT data FROM {table}')]

    def put(self, table, key, data):
        with self.conn() as c:
            c.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (key, encoded(data)))

    def plan(self, pid):
        self.base(pid)
        return self.get('learning_plans', pid)

    def lessons(self, pid):
        with self.conn() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT data FROM learning_lessons WHERE plan_id=? ORDER BY lesson_no', (pid,))]

    def version(self, pid):
        p = self.plan(pid)
        with self.conn() as c:
            row = c.execute('SELECT data FROM learning_plan_versions WHERE plan_id=? AND version=?', (pid, p['version'])).fetchone()
        return json.loads(row[0])

    def check_files(self, plan, overrides=None):
        for rel, expected in plan.get('hashes', {}).items():
            actual = self.hash(rel)
            if actual != expected and not (rel in (overrides or {}) and overrides[rel] == actual):
                fail('conflict', f'文件被外部修改：{rel}。请核对后导入规划或恢复文件。')

    def replay(self, key, request):
        with self.conn() as c: row = c.execute('SELECT data FROM learning_publications WHERE id=?', (key,)).fetchone()
        if not row: return None
        data = json.loads(row[0])
        if data['request'] != digest(encoded(request)): fail('conflict', '相同请求标识不能用于不同操作。')
        if data['state'] != 'done': fail('pending', '有未完成写入，请先检查恢复。')
        return data['result']

    def publish(self, key, request, files, sql, result):
        # Caller holds the short global writer lock. Disk and SQLite are journaled, not presumed atomic.
        if self.rows('learning_publications'):
            self.recover_locked()
        replay = self.replay(key, request)
        if replay is not None: return replay
        changes = {rel: {'before': self.hash(rel), 'text': value, 'after': digest(value)} for rel, value in files.items()}
        journal = {'state': 'pending', 'request': digest(encoded(request)), 'files': changes, 'sql': sql, 'result': result}
        self.put('learning_publications', key, journal)
        self.finish(key, journal)
        return result

    def finish(self, key, journal):
        # Preflight every target before touching any file.
        for rel, change in journal['files'].items():
            if self.hash(rel) not in (change['before'], change['after']): fail('conflict', f'恢复检测到人工改动：{rel}')
        for rel, change in journal['files'].items():
            p = self.path(rel)
            if self.hash(rel) == change['after']: continue
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.publish-', dir=p.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(change['text']); stream.flush(); os.fsync(stream.fileno())
                os.replace(name, p)
            finally:
                if os.path.exists(name): os.unlink(name)
        with self.conn() as c:
            for statement, parameters in journal['sql']: c.execute(statement, parameters)
            journal['state'] = 'done'
            c.execute('UPDATE learning_publications SET data=? WHERE id=?', (encoded(journal), key))

    def recover_locked(self):
        for row in self.rows('learning_publications'):
            if row['state'] == 'pending':
                with self.conn() as c:
                    key = c.execute('SELECT id FROM learning_publications WHERE data=?', (encoded(row),)).fetchone()[0]
                self.finish(key, row)

    def read_draft(self, did):
        d = self.get('learning_drafts', did)
        d['content_hash'] = content_hash(d)
        d['family_id'] = d.get('family_id', did)
        family = self.get('learning_draft_families', d['family_id'])
        d['family_published'] = family.get('published_draft_id')
        if d['kind']=='plan':d['budget']=self.budget(d['brief'],d.get('plan_id'))
        d['sections'] = sections(d.get('content','')) if d['kind']=='course' else []
        d['frozen_lessons'] = [l['lesson_no'] for l in self.lessons(d['plan_id'])] if d.get('plan_id') else []
        parent = d.get('parent_draft_id')
        d['diff'] = differences(self.get('learning_drafts',parent),d) if parent else []
        return d

    def parent(self, did, expected_hash, kind):
        self.recover_locked()
        d = self.get('learning_drafts', did)
        if d['kind']!=kind or d['state']=='published' or (kind=='course' and not d.get('complete')):
            fail('conflict','该草稿不能继续修改，请从当前正式规划开始修订。')
        if not expected_hash or content_hash(d)!=expected_hash: fail('conflict','草稿基线已变化，请重新读取。')
        self.check_family(d)
        if kind=='plan' and d.get('plan_id') and self.plan(d['plan_id'])['version']!=d['base_version']:
            fail('conflict','正式规划已改变，请从当前版本重新修订。')
        if kind=='course':
            current=self.course_context(d['context']['plan_id'])
            if any(current[k]!=d['context'][k] for k in ('base_version','lesson_no','source_hash')):
                fail('conflict','规划或资料已改变，请重新生成课程。')
        return d

    def check_family(self, d):
        family=self.get('learning_draft_families',d.get('family_id',d['id']))
        if family.get('published_draft_id'):fail('conflict','本组草稿已有版本正式保存，请从正式版本开始后续修订。')
        return family

    def family_sql(self, d, target):
        family=self.check_family(d)
        family.update(published_draft_id=d['id'], target=target)
        return ('UPDATE learning_draft_families SET data=? WHERE id=?',[encoded(family),family['id']])

    def save_draft_locked(self, d, parent=None, operation='manual', instruction=None, scope=None):
        if parent and payload(parent)==payload(d):return self.read_draft(parent['id'])
        d.update(family_id=parent.get('family_id',parent['id']) if parent else d['id'],
                 parent_draft_id=parent['id'] if parent else None, operation=operation,
                 instruction=instruction, scope=scope)
        if parent and parent.get('evidence_snapshot_id'):d.setdefault('evidence_snapshot_id',parent['evidence_snapshot_id'])
        with self.conn() as c:
            if not parent:c.execute('INSERT INTO learning_draft_families VALUES (?,?)',(d['family_id'],encoded({'id':d['family_id'],'published_draft_id':None})))
            c.execute('INSERT INTO learning_drafts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(d['id'],encoded(d)))
            if d.get('evidence_snapshot_id'):
                from ai_evidence import bind
                bind(c,'plan-draft',d['id'],d['evidence_snapshot_id'])
        return self.read_draft(d['id'])

    def draft(self, data):
        with self.lock():
            parent=self.parent(data['parent_draft_id'],data.get('parent_hash'),'plan') if data.get('parent_draft_id') else None
            b = brief(data.get('brief')); doc = document(data.get('document'), b)
            pid = parent.get('plan_id') if parent else data.get('plan_id')
            base_version = parent.get('base_version',0) if parent else data.get('base_version', 0)
            if pid and base_version != self.plan(pid)['version']: fail('conflict', '规划版本已改变。')
            overrides = copy.deepcopy(parent.get('overrides',{})) if parent else {}
            if data.get('external_hash') and pid:
                rel = self.base(pid) + '/学习规划.md'
                if self.hash(rel) != data['external_hash']: fail('conflict', '外部文件已再次变化。')
                overrides[rel] = data['external_hash']
            if parent and pid:
                old=self.version(pid)['document']['lessons']
                for lesson in self.lessons(pid):
                    n=lesson['lesson_no']
                    if n>len(doc['lessons']) or doc['lessons'][n-1]!=old[n-1]:fail('conflict','已发布课次不能修改或移动。')
            d = {'id': str(uuid.uuid4()), 'kind': 'plan', 'brief': b, 'document': doc, 'plan_id': pid,
                 'base_version': base_version, 'overrides': overrides, 'state': 'ready', 'created_at': now()}
            for k in ('continuation_id','continuation_form_hash'):
                if (parent or data).get(k):d[k]=(parent or data)[k]
            if data.get('evidence_snapshot_id'):d['evidence_snapshot_id']=data['evidence_snapshot_id']
            return self.save_draft_locked(d,parent,data.get('operation','manual'),data.get('instruction'),data.get('scope'))

    def draft_history(self, did, offset=0, limit=20):
        d=self.read_draft(did); family=d['family_id']
        rows=[x for x in self.rows('learning_drafts') if x.get('family_id',x['id'])==family]
        rows.sort(key=lambda x:(x.get('created_at',''),x['id']))
        return {'items':[{k:x.get(k) for k in ('id','parent_draft_id','created_at','operation','instruction','state')} for x in rows[offset:offset+limit]],
                'next_offset':offset+limit if offset+limit<len(rows) else None, 'total':len(rows)}

    def budget(self, candidate=None, replacing=None):
        settings = {r['id']: r for r in self.rows('learning_settings')}
        setting = settings.get('budget', {'weekly': None, 'legacy_weekly': None})
        total = sum(p['brief']['sessions'] * p['brief']['minutes'] for p in self.rows('learning_plans')
                    if p['id'] != replacing and p['status'] == 'active' and p['brief'].get('pacing')!='self_paced')
        if candidate and candidate.get('pacing')!='self_paced': total += candidate['sessions'] * candidate['minutes']
        unallocated=sum(p['id']!=replacing and p['status']=='active' and p['brief'].get('pacing')=='self_paced' for p in self.rows('learning_plans'))
        if candidate and candidate.get('pacing')=='self_paced':unallocated+=1
        legacy = setting.get('legacy_weekly')
        total += legacy or 0
        limit = setting.get('weekly')
        return {'weekly': limit, 'legacy_weekly': legacy, 'known_minutes': total, 'self_paced_count':unallocated,
                'legacy_unknown': legacy is None, 'over': max(0, total - limit) if limit is not None else None}

    def adopt(self, did, key, accept_over=False, expected_hash=None):
        request = {'op': 'adopt', 'draft': did, 'accept_over': accept_over}
        if expected_hash:request['expected_hash']=expected_hash
        with self.lock():
            self.recover_locked()
            old = self.replay(key, request)
            if old is not None: return old
            d = self.get('learning_drafts', did)
            if d['kind'] != 'plan' or d['state'] != 'ready': fail('conflict', '规划草稿尚未就绪。')
            self.check_family(d)
            if expected_hash and content_hash(d)!=expected_hash:fail('conflict','草稿已变化，请重新预览。')
            b, doc = brief(d['brief']), document(d['document'], d['brief'])
            if self.budget(b, d.get('plan_id'))['over'] and not accept_over: fail('budget', '超出每周预算，请调整规划或明确接受超额。')
            pid = d.get('plan_id'); files = {}
            if pid:
                p = self.plan(pid)
                if p['version'] != d['base_version']: fail('conflict', '规划版本已改变。')
                self.check_files(p, d.get('overrides'))
                existing = self.version(pid)['document']['lessons']
                for lesson in self.lessons(pid):
                    n = lesson['lesson_no']
                    if n > len(doc['lessons']) or existing[n-1] != doc['lessons'][n-1]:
                        fail('conflict', '已发布课程必须完整保留，包括尚未学完的课。')
                p['version'] += 1
                for rel in d.get('overrides', {}):
                    files[f'{self.base(pid)}/规划历史/外部修改-v{p["version"]:03d}.md'] = self.read_text(rel)
            else:
                prefix = 'plan-' + now()[:10].replace('-', '') + '-'
                numbers = [int(p['id'].rsplit('-',1)[1]) for p in self.rows('learning_plans') if p['id'].startswith(prefix)]
                pid = prefix + f'{max(numbers, default=0)+1:03d}'
                if self.exists(self.base(pid)): fail('conflict', '计划目录已存在，请检查未登记内容。')
                p = {'id': pid, 'version': 1, 'status': 'active', 'created_at': now(), 'hashes': {}}
                if not getattr(self,'remote',False):
                    files[f'{self.base(pid)}/学习记录.md'] = '# 学习记录\n\n## 个人笔记\n\n请在此保留自己的练习、疑问和记录。\n'
                files[f'{self.base(pid)}/课程目录.md'] = '# 已发布课程\n\n| 课次 | 日期 | 课程 | 资料 |\n|---|---|---|---|\n'
                files[f'{self.base(pid)}/README.md'] = ('# 学习计划\n\n[规划](学习规划.md) · [课程目录](课程目录.md)\n' if getattr(self,'remote',False) else '# 学习计划\n\n[规划](学习规划.md) · [课程目录](课程目录.md) · [学习记录](学习记录.md)\n')
            p.update(brief=b, name=b['title'])
            base = self.base(pid)
            files[base+'/学习规划.md'] = plan_markdown(b, doc)
            files[f'{base}/规划历史/v{p["version"]:03d}.md'] = files[base+'/学习规划.md']
            mirror = {k: v for k,v in p.items() if k != 'hashes'}
            mirror['schema_version'] = 1
            files[base+'/计划信息.json'] = encoded(mirror)
            p['hashes'].update({rel: digest(value) for rel,value in files.items() if not rel.endswith('/学习记录.md')})
            v = {'brief': b, 'document': doc, 'created_at': now()}
            d['state'] = 'published'
            sql = [('INSERT INTO learning_plans VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', [pid, encoded(p)]),
                   ('INSERT INTO learning_plan_versions VALUES (?,?,?)', [pid,p['version'],encoded(v)]),
                   ('UPDATE learning_drafts SET data=? WHERE id=?', [encoded(d),did])]
            if d.get('evidence_snapshot_id'):
                from ai_evidence import link_statement
                sql.append(link_statement('plan-result',pid,d['evidence_snapshot_id'],str(p['version'])))
            sql.append(self.family_sql(d,{'plan_id':pid,'version':p['version']}))
            return self.publish(key, request, files, sql, {'plan_id': pid, 'version': p['version']})

    def save_sources(self, pid, entries):
        entries = sources(entries)
        with self.lock():
            p = self.plan(pid); self.check_files(p)
            n = len(self.lessons(pid)) + 1
            if n > len(self.version(pid)['document']['lessons']): fail('conflict', '当前规划课程已生成完毕。')
            rel = f'{self.base(pid)}/备课资料/第{n:03d}课.json'
            files = {rel: encoded(entries)}
            p['hashes'].update({k:digest(v) for k,v in files.items()})
            return self.publish(str(uuid.uuid4()), {'sources':pid,'n':n,'entries':entries}, files,
                                [('UPDATE learning_plans SET data=? WHERE id=?',[encoded(p),pid])], {'lesson_no': n})

    def course_context(self, pid):
        p = self.plan(pid); self.check_files(p)
        if p['status'] != 'active': fail('conflict', '计划已暂停，请先恢复。')
        lessons = self.lessons(pid); n = len(lessons)+1
        if not getattr(self,'remote',False) and any(l['date'] == now()[:10] for l in lessons): fail('conflict', '本计划今天已有完整课程，请明天继续或选择其他计划。')
        if getattr(self,'remote',False) and any(l['learning_state']!='completed' for l in lessons):fail('conflict','请先学完已发布课次。')
        doc = self.version(pid)['document']
        if n > len(doc['lessons']): fail('conflict', '当前规划课程已生成完毕，请修订或新建计划。')
        rel = f'{self.base(pid)}/备课资料/第{n:03d}课.json'
        if not self.exists(rel): fail('sources', '请先准备备课资料。')
        entries = sources(json.loads(self.read_text(rel)))
        return {'plan_id':pid, 'base_version':p['version'], 'lesson_no':n, 'date':now()[:10],
                'brief':p['brief'], 'lesson':doc['lessons'][n-1], 'source_entries':entries,
                'source_hash':self.hash(rel), 'previous_topics':[x['topic'] for x in lessons[-3:]]}

    def validate_course(self, d):
        content, notes = d.get('content',''), d.get('sources','')
        if not content.strip() or not notes.strip(): fail('invalid','正文或参考资料为空。',422)
        for name in ('引导问题','概念','示范','边界','练习','参考分析','自查','记忆提示'):
            if name not in content: fail('invalid',f'正文缺少{name}。',422)
        n = d['context']['lesson_no']
        if not re.search(rf'^#\s*第0*{n}课',content,re.M) or d['context']['date'] not in content:
            fail('invalid','正文课号或日期不正确。',422)
        exercise = re.search(r'^#{1,6}[^\n]*练习[^\n]*$', content, re.M)
        analysis = re.search(r'^#{1,6}[^\n]*参考分析[^\n]*$', content, re.M)
        if not exercise or not analysis or '\n---\n' not in content[exercise.end():analysis.start()]:
            fail('invalid','请在练习之后、参考分析标题之前添加独立分隔线。',422)
        allowed_urls = {e.get('url') for e in d['context']['source_entries'] if e.get('url')}
        for entry in d['context']['source_entries']:
            allowed_urls.update(re.findall(r'https?://[^\s<>\)\]\"，。；]+',entry.get('content','')))
        if allowed_urls:
            urls = set(re.findall(r'https?://[^\s<>\)\]"，。；]+', content+'\n'+notes))
            if not urls or not urls <= allowed_urls: fail('invalid','引用链接必须来自已准备资料清单。',422)
            for target in re.findall(r'\]\(([^)]+)\)', content+'\n'+notes):
                if target not in allowed_urls: fail('invalid','正文与摘要只能引用清单内链接。',422)
        if not allowed_urls and d['context'].get('strict_sources') and re.search(r'https?://|\]\(',content+'\n'+notes):
            fail('invalid','本课未提供链接资料，不能加入未经提供的引用链接。',422)
        if '<script' in content.lower() or '<script' in notes.lower(): fail('invalid','内容含不可接受的脚本。',422)

    def course_draft(self, context, content, notes, complete=True, parent_id=None, parent_hash=None, operation='manual', instruction=None, scope=None, evidence_snapshot_id=None):
        with self.lock():
            parent=self.parent(parent_id,parent_hash,'course') if parent_id else None
            if parent and context!=parent['context']:fail('conflict','不能静默改变课程上下文。')
            d = {'id':str(uuid.uuid4()), 'kind':'course', 'context':copy.deepcopy(context), 'content':content, 'sources':notes,
                 'complete':complete, 'state':'ready', 'created_at':now()}
            if evidence_snapshot_id:d['evidence_snapshot_id']=evidence_snapshot_id
            try: self.validate_course(d)
            except Exception:
                if parent:raise
                d['state']='failed'
            if not complete: d['state']='failed'
            return self.save_draft_locked(d,parent,operation,instruction,scope)

    def redate_course(self, did, expected_hash):
        with self.lock():
            parent=self.parent(did,expected_hash,'course')
            old_date=parent['context']['date']; today=now()[:10]
            if old_date==today:return self.read_draft(did)
            d=copy.deepcopy(parent);d.update(id=str(uuid.uuid4()),created_at=now())
            d['context']['date']=today
            parts=sections(d['content']);end=parts[0]['start'] if parts else len(d['content'])
            d['content']=d['content'][:end].replace(old_date,today)+d['content'][end:]
            self.validate_course(d);d['state']='ready'
            return self.save_draft_locked(d,parent,'redate')

    def publish_course(self, did, key, expected_hash=None):
        request={'op':'course','draft':did}
        if expected_hash:request['expected_hash']=expected_hash
        with self.lock():
            self.recover_locked()
            old=self.replay(key,request)
            if old is not None:return old
            d=self.get('learning_drafts',did)
            if d['kind']!='course' or not d.get('complete') or d['state']!='ready':fail('conflict','课程尚未完整生成并通过校验。')
            self.check_family(d)
            if expected_hash and content_hash(d)!=expected_hash:fail('conflict','草稿已变化，请重新预览。')
            self.validate_course(d)
            ctx=d['context']; pid=ctx['plan_id']; n=ctx['lesson_no']; p=self.plan(pid)
            if ctx.get('extension'):
                from .continuation import extension_context
                current=extension_context(self,pid)
            else:current=self.course_context(pid)
            if current['base_version']!=ctx['base_version'] or current['lesson_no']!=n or current['source_hash']!=ctx['source_hash']:
                fail('conflict','规划、课次或备课资料已变更，请重新核对。')
            if ctx['date']!=now()[:10]:fail('conflict','草稿日期已过期，请编辑为今天日期后保存。')
            title=re.sub(r'[^\w\u4e00-\u9fff-]+','-',ctx['lesson']['topic']).strip('-')[:60] or '课程'
            course=f'每日课程/{ctx["date"]}-第{n:03d}课-{title}.md'; source=f'参考资料/第{n:03d}课-参考资料.md';base=self.base(pid)
            if self.exists(base+'/'+course) or self.exists(base+'/'+source):fail('conflict','课程或资料已存在。')
            files={base+'/'+course:d['content']+f'\n\n[参考资料](../{source})\n',
                   base+'/'+source:f'# 第{n:03d}课参考资料\n\n[对应课程](../{course})\n\n'+d['sources']}
            index=base+'/课程目录.md'
            topic=ctx['lesson']['topic'].replace('|','／').replace('\n',' ')
            files[index]=self.read_text(index)+f'| {n:03d} | {ctx["date"]} | [{topic}]({course}) | [资料]({source}) |\n'
            extension_sql=[]
            if ctx.get('extension'):
                from .continuation import extension_publication
                extra,extension_sql=extension_publication(self,p,ctx);files.update(extra)
            p['hashes'].update({k:digest(v) for k,v in files.items()})
            lesson={'lesson_no':n,'topic':ctx['lesson']['topic'],'date':ctx['date'],'path':course,'source':source,
                    'version':p['version'],'learning_state':'unknown','learning_label':'待本人反馈'}
            if d.get('evidence_snapshot_id'):
                from ai_evidence import link_statement
                extension_sql.append(link_statement('plan-course',pid+'/'+str(n),d['evidence_snapshot_id']))
            d['state']='published'
            return self.publish(key,request,files,[('INSERT INTO learning_lessons VALUES (?,?,?)',[pid,n,encoded(lesson)]),
                ('UPDATE learning_plans SET data=? WHERE id=?',[encoded(p),pid]),
                ('UPDATE learning_drafts SET data=? WHERE id=?',[encoded(d),did]),
                self.family_sql(d,{'plan_id':pid,'lesson_no':n}),*extension_sql],{'plan_id':pid,'lesson_no':n,'path':self.file_location(base+'/'+course)})

    def feedback(self, pid, n, data, key):
        state=data.get('state')
        if state not in ('completed','unknown'):fail('invalid','学习状态无效。',422)
        comment=data.get('comment','')
        if not isinstance(comment,str) or len(comment)>4000:fail('invalid','反馈过长。',422)
        request={'op':'feedback','plan_id':pid,'lesson_no':n,'state':state,'comment':comment}
        with self.lock():
            self.recover_locked()
            old=self.replay(key,request)
            if old is not None:return old
            p=self.plan(pid);self.check_files(p)
            lesson=next((x for x in self.lessons(pid) if x['lesson_no']==n),None)
            if not lesson:fail('not_found','课程不存在。',404)
            lesson.update(learning_state=state,learning_label='本人确认完成' if state=='completed' else '待本人反馈')
            feedback={'state':state,'comment':comment,'date':now()}
            rel=self.base(pid)+'/学习记录.md'
            current=self.read_text(rel)
            updated=current+f'\n## 第{n:03d}课反馈 · {now()}\n\n{lesson["learning_label"]}\n\n{comment}\n'
            return self.publish(key,request,{rel:updated},[
                ('UPDATE learning_lessons SET data=? WHERE plan_id=? AND lesson_no=?',[encoded(lesson),pid,n]),
                ('INSERT INTO learning_feedback VALUES (?,?,?) ON CONFLICT(plan_id,lesson_no) DO UPDATE SET data=excluded.data',[pid,n,encoded(feedback)])],feedback)
