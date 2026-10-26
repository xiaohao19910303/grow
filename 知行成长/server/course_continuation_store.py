"""Tenant-local continuation state, revision guards and durable request receipts."""
from contextlib import contextmanager
import json
import db
from copilot.core import encoded, fail

TABLES='''CREATE TABLE IF NOT EXISTS course_continuations (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS course_continuation_jobs (id TEXT PRIMARY KEY,data TEXT NOT NULL);'''

@contextmanager
def connection(lock=None):
    with db.connect() as c:
        if c.execute("SELECT to_regclass('course_continuations')").fetchone()[0] is None:
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':course-continuations-schema',0))")
            c.executescript(TABLES)
        if lock:c.execute('SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ?,0))',(':course-continuation:'+lock,))
        yield c

def get(c,table,id,required=True):
    row=c.execute(f'SELECT data FROM {table} WHERE id=?',(id,)).fetchone()
    if not row and required:fail('not_found','学习接续记录不存在。',404)
    return json.loads(row[0]) if row else None

def put(c,table,value):
    c.execute(f'INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(value['id'],encoded(value)))

def rows(c,table):return [json.loads(r[0]) for r in c.execute(f'SELECT data FROM {table}')]
