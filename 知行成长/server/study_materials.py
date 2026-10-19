"""Shared bundled lessons with private, tenant-scoped PostgreSQL learning records."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import db
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from tenancy import current_user

MODULES = {
    'yingyu': ('英文阅读', '每日文章', '35 分钟'),
    'biaoda': ('结构化表达', '每日练习', '15 分钟'),
}


def initialize():
    from cloud_content import TABLES
    with db.connect() as c:
        c.executescript(TABLES)
        c.executescript('''CREATE TABLE IF NOT EXISTS study_generated_courses (id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS study_generation_jobs (id TEXT PRIMARY KEY,data TEXT NOT NULL);''')
        c.executescript('''CREATE TABLE IF NOT EXISTS study_learning_records (
            module_id TEXT NOT NULL CHECK(module_id IN ('yingyu','biaoda')),
            filename TEXT NOT NULL, lesson_no INTEGER NOT NULL CHECK(lesson_no>0),
            topic TEXT NOT NULL, summary_text TEXT NOT NULL DEFAULT '',
            time_spent_seconds INTEGER NOT NULL CHECK(time_spent_seconds>=0),
            completed_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision>0),
            request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
            PRIMARY KEY(module_id,filename));''')


class Completion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary_text: str = Field(default='', max_length=10000)
    time_spent_seconds: int = Field(ge=0, le=86400, strict=True)
    version: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: int = Field(ge=0, strict=True)
    key: str = Field(min_length=8, max_length=160)


def public_record(row):
    if row is None:
        return None
    return {**{k: v for k, v in dict(row).items() if k not in ('request_key', 'request_hash')},
            'module_name': MODULES[row['module_id']][0]}


class Materials:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def conn(self):
        return db.connect()

    def files(self, module):
        if module not in MODULES:
            raise HTTPException(404, '未找到学习模块。')
        name, folder, _ = MODULES[module]
        directory = self.root / name / folder
        return [p for p in sorted(directory.glob('*.md')) if p.is_file()
                and p.resolve().is_relative_to(directory.resolve())
                and p.resolve().is_relative_to(self.root)]

    def record(self, module, filename):
        with db.connect() as c:
            row = c.execute('SELECT * FROM study_learning_records WHERE module_id=? AND filename=?',
                            (module, filename)).fetchone()
        return public_record(row)

    def lessons(self, module):
        user = current_user.get()
        # Only the original owner inherits progress from the original Markdown.
        record_path = self.root / MODULES[module][0] / '学习记录.md'
        legacy = record_path.read_text(encoding='utf-8') if (not user or user['is_owner']) and record_path.is_file() else ''
        with db.connect() as c:
            records = {r['filename']: public_record(r) for r in c.execute(
                'SELECT * FROM study_learning_records WHERE module_id=?', (module,)).fetchall()}
            generated = [json.loads(r[0]) for r in c.execute(
                "SELECT data FROM study_generated_courses WHERE data::jsonb->>'module_id'=?", (module,)).fetchall()]
        result = []
        for index, path in enumerate(self.files(module), 1):
            body = path.read_text(encoding='utf-8')
            title = re.search(r'^#\s+(.+)', body, re.M)
            day = re.search(r'Day\s*(\d+)', path.stem, re.I)
            stamp = re.match(r'(\d{4}-\d{2}-\d{2})', path.name) or re.search(r'日期[：:]\s*(\d{4}-\d{2}-\d{2})', body.replace('**', ''))
            status = '待本人反馈'
            if module == 'yingyu' and day:
                rows = [cells for line in legacy.splitlines()
                        if len(cells := [x.strip() for x in line.strip().strip('|').split('|')]) >= 3
                        and re.fullmatch(r'Day\s*0*' + str(int(day[1])), cells[1], re.I)]
                if len(rows) == 1:
                    status = rows[0][2] or status
            record = records.get(path.name)
            completed = bool(record) or status.startswith(('已完成', '已学习')) or status in ('完成', '✅', '[x]', '[X]')
            result.append({'filename': path.name, 'lesson_no': int(day[1]) if day else index,
                           'topic': title[1] if title else path.stem, 'date': stamp[1] if stamp else '',
                           'learning_label': '本人确认完成' if record else status,
                           'learning_state': 'completed' if completed else 'unknown',
                           'version': hashlib.sha256(body.encode()).hexdigest(),
                           'record_revision': record['revision'] if record else 0,
                           'completed_at': record['completed_at'] if record else None})
        for course in generated:
            record = records.get(course['filename'])
            result.append({**course, 'date': '', 'learning_state': 'completed' if record else 'unknown',
                           'learning_label': '本人确认完成' if record else '待本人反馈',
                           'record_revision': record['revision'] if record else 0,
                           'completed_at': record['completed_at'] if record else None})
        return sorted(result, key=lambda x: x['lesson_no'])

    def lesson(self, module, filename):
        if module not in MODULES:
            raise HTTPException(404, '未找到学习模块。')
        lesson = next((x for x in self.lessons(module) if x['filename'] == filename), None)
        if lesson is None:
            raise HTTPException(404, '未找到课程。')
        if lesson.get('content_path'):
            from cloud_content import Documents
            documents = Documents(self)
            body = documents.read(lesson['content_path'])
            metadata = documents.metadata(lesson['content_path'])
            lesson['github_url'] = documents.content.url(lesson['content_path'], metadata['commit_sha'])
        else:
            body = (self.root / MODULES[module][0] / MODULES[module][1] / filename).read_text(encoding='utf-8')
        lesson['version'] = hashlib.sha256(body.encode()).hexdigest()
        return {'content': body, 'lesson': lesson, 'record': self.record(module, filename)}

    def save(self, module, filename, body):
        lesson = self.lesson(module, filename)['lesson']
        if body.version != lesson['version']:
            raise HTTPException(409, '课程内容已更新，请先保留笔记并重新读取课程。')
        request_hash = hashlib.sha256(json.dumps(body.model_dump(exclude={'key'}), sort_keys=True).encode()).hexdigest()
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
        with db.connect() as c:
            # Serialize first inserts and updates to the same course within one account.
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ?,0))',
                      (':study:' + module + ':' + filename,))
            old = c.execute('SELECT * FROM study_learning_records WHERE module_id=? AND filename=? FOR UPDATE',
                            (module, filename)).fetchone()
            if old and old['request_key'] == body.key:
                if old['request_hash'] != request_hash:
                    raise HTTPException(409, '重复请求的内容不同，请重新保存。')
                return public_record(old)
            if body.revision != (old['revision'] if old else 0):
                raise HTTPException(409, '学习记录已在其他页面更新；当前笔记仍保留，请先核对已有记录。')
            completed_at = old['completed_at'] if old else stamp
            seconds = old['time_spent_seconds'] if old else body.time_spent_seconds
            row = c.execute('''INSERT INTO study_learning_records
                (module_id,filename,lesson_no,topic,summary_text,time_spent_seconds,completed_at,updated_at,revision,request_key,request_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(module_id,filename) DO UPDATE SET
                summary_text=excluded.summary_text,updated_at=excluded.updated_at,revision=excluded.revision,
                request_key=excluded.request_key,request_hash=excluded.request_hash RETURNING *''',
                (module, filename, lesson['lesson_no'], lesson['topic'], body.summary_text, seconds,
                 completed_at, stamp, body.revision + 1, body.key, request_hash)).fetchone()
        return public_record(row)


def register(app, root):
    materials = Materials(root)
    from study_generation import MaterialGenerator, install_routes
    from tenancy import scoped
    materials.generator = scoped(app, lambda: MaterialGenerator(materials))

    def private(response: Response, request: Request):
        response.headers['Cache-Control'] = 'no-store'
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and (
                request.headers.get('X-Copilot-Request') != '1'
                or request.headers.get('Origin', origin) != origin
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise HTTPException(403, '保存和生成课程需要同源请求。')

    router = APIRouter(prefix='/api/study-materials', dependencies=[Depends(private)])

    @router.get('')
    def modules():
        return {'modules': [{'id': module, 'name': name, 'duration': duration, 'lessons': materials.lessons(module),
                             'generation': materials.generator.latest(module)}
                            for module, (name, _, duration) in MODULES.items()]}

    @router.get('/learning-history')
    def history(start: date, end: date):
        if not 0 <= (end - start).days <= 366:
            raise HTTPException(422, '请选择不超过一年的日期范围。')
        with db.connect() as c:
            rows = c.execute('''SELECT * FROM study_learning_records WHERE completed_at>=? AND completed_at<?
                ORDER BY completed_at DESC,module_id,lesson_no''',
                (start.isoformat(), (end + timedelta(days=1)).isoformat())).fetchall()
        return {'total': len(rows), 'items': [public_record(r) for r in rows]}

    install_routes(router, materials.generator)

    @router.get('/{module}/{filename}')
    def lesson(module: str, filename: str):
        return materials.lesson(module, filename)

    @router.get('/{module}/{filename}/learning-record')
    def record(module: str, filename: str):
        materials.lesson(module, filename)
        return materials.record(module, filename)

    @router.post('/{module}/{filename}/learning-record')
    def complete(module: str, filename: str, body: Completion, request: Request):
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if (request.headers.get('X-Copilot-Request') != '1'
                or request.headers.get('Origin', origin) != origin
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise HTTPException(403, '保存学习记录需要同源请求。')
        return materials.save(module, filename, body)

    app.include_router(router)
    return materials
