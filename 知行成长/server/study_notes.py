"""Private course notes and exercise drafts, independent of completion records."""
from contextlib import contextmanager
import hashlib
import json
from typing import Literal

import db
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from copilot.core import now

TABLES = '''CREATE TABLE IF NOT EXISTS course_study_notes (
    kind TEXT NOT NULL, course_id TEXT NOT NULL, data TEXT NOT NULL,
    revision INTEGER NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY(kind,course_id));'''


def initialize(connection=None):
    if connection is not None:
        if connection.execute("SELECT to_regclass('course_study_notes')").fetchone()[0] is None:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':course-study-notes-schema',0))")
            connection.executescript(TABLES)
    else:
        with db.connect() as c:
            initialize(c)


@contextmanager
def connection():
    # Existing accounts also receive this additive table on first use.
    with db.connect() as c:
        initialize(c)
        yield c


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str = Field(max_length=10000)
    answers: dict[str, str]
    version: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: int = Field(ge=0, strict=True)
    key: str = Field(min_length=8, max_length=160)

    @field_validator('answers')
    @classmethod
    def bounded_answers(cls, value):
        if len(value) > 100 or any(not k or len(k) > 500 or len(v) > 10000 for k, v in value.items()) or sum(map(len, value.values())) > 60000:
            raise ValueError('练习答案过长，请精简后暂存。')
        return value


def public(row):
    return {**json.loads(row['data']), 'revision': row['revision'], 'updated_at': row['updated_at']} if row else None


def register(app):
    router = APIRouter(prefix='/api/study-notes')

    @router.api_route('/{kind}/{course:path}', methods=['GET', 'PUT'])
    def notes(kind: Literal['yingyu', 'biaoda', 'renzhi', 'plan'], course: str, request: Request, body: Draft | None = None):
        if not course or len(course) > 500 or any(part in ('', '.', '..') for part in course.split('/')) or any(ord(ch) < 32 for ch in course):
            raise HTTPException(422, '课程标识无效。')
        if request.method == 'GET':
            with connection() as c:
                return public(c.execute('SELECT * FROM course_study_notes WHERE kind=? AND course_id=?', (kind, course)).fetchone())
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if request.headers.get('X-Copilot-Request') != '1' or request.headers.get('Origin', origin) != origin or request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise HTTPException(403, '暂存学习内容需要同源请求。')
        if body is None:
            raise HTTPException(422, '请提供笔记与练习答案。')
        data = body.model_dump(exclude={'key', 'revision'})
        request_hash = hashlib.sha256(json.dumps(body.model_dump(exclude={'key'}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ?,0))', (':study-notes:' + kind + ':' + course,))
            old = c.execute('SELECT * FROM course_study_notes WHERE kind=? AND course_id=? FOR UPDATE', (kind, course)).fetchone()
            if old and old['request_key'] == body.key:
                if old['request_hash'] != request_hash:
                    raise HTTPException(409, '重复请求内容不同，当前输入仍可保留在本机。')
                return public(old)
            if body.revision != (old['revision'] if old else 0):
                raise HTTPException(409, '另一页面已更新笔记，请先核对；当前输入已保留在本机。')
            row = c.execute('''INSERT INTO course_study_notes VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(kind,course_id) DO UPDATE SET data=excluded.data,revision=excluded.revision,
                request_key=excluded.request_key,request_hash=excluded.request_hash,updated_at=excluded.updated_at
                RETURNING *''', (kind, course, json.dumps(data, ensure_ascii=False), body.revision + 1, body.key, request_hash, now())).fetchone()
            return public(row)

    @app.middleware('http')
    async def private(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/study-notes/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.include_router(router)
