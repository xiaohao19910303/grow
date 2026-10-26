"""Private course start/resume metadata; never a source of completion evidence."""
from contextlib import contextmanager

import db
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from copilot.core import now


TABLES = '''CREATE TABLE IF NOT EXISTS course_learning_activity (
    course_key TEXT PRIMARY KEY, lesson_no INTEGER NOT NULL CHECK(lesson_no>0),
    started_at TEXT NOT NULL, last_opened_at TEXT NOT NULL);'''


@contextmanager
def connection():
    with db.connect() as c:
        if c.execute("SELECT to_regclass('course_learning_activity')").fetchone()[0] is None:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':course-activity-schema',0))")
            c.executescript(TABLES)
        yield c


class Activity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    course_key: str = Field(pattern=r'^(renzhi|yingyu|biaoda|plan:[A-Za-z0-9_-]{1,160})$')
    lesson_no: int = Field(ge=1, le=1000000, strict=True)


def install_routes(router):
    @router.get('/library/activity')
    def listing(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with connection() as c:
            return {'items': [dict(r) for r in c.execute('SELECT * FROM course_learning_activity ORDER BY course_key')]}

    @router.post('/library/activity')
    def opened(body: Activity, request: Request, response: Response):
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if (request.headers.get('X-Copilot-Request') != '1'
                or request.headers.get('Origin', origin) != origin
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            raise HTTPException(403, '保存课程学习位置需要同源请求。')
        response.headers['Cache-Control'] = 'no-store'
        stamp = now()
        with connection() as c:
            row = c.execute('''INSERT INTO course_learning_activity VALUES (?,?,?,?)
                ON CONFLICT(course_key) DO UPDATE SET lesson_no=excluded.lesson_no,
                last_opened_at=excluded.last_opened_at RETURNING *''',
                (body.course_key, body.lesson_no, stamp, stamp)).fetchone()
            return dict(row)
