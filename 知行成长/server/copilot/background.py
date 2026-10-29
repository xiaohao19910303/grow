"""Account-scoped, idempotent workers; HTTP clients only observe persisted state."""
import asyncio
import json
import threading
import time
import uuid
import sqlite3

from .ai_config import require_config
from .core import digest, encoded, fail, now
from .summary import SummaryGenerator

ACTIVE=('queued','generating')

class BackgroundGenerations:
    def __init__(self,store,summary=None):
        self.store=store;self.summary=summary or SummaryGenerator(store)
        self.tasks={};self.worker=uuid.uuid4().hex;self.initialized=False;self.mutex=threading.RLock()

    def initialize(self):
        with self.mutex:
            if self.initialized:return
            with self.store.conn() as c:
                c.executescript('''CREATE TABLE IF NOT EXISTS copilot_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,module_id TEXT NOT NULL DEFAULT 'renzhi',round_id INTEGER NOT NULL DEFAULT 1,
                    scope TEXT NOT NULL DEFAULT 'full_course',content TEXT NOT NULL,feedback_snapshot TEXT,created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS copilot_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,module_id TEXT NOT NULL DEFAULT 'renzhi',round_id INTEGER NOT NULL DEFAULT 1,
                    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
                    mastery_level TEXT NOT NULL CHECK(mastery_level IN ('fully_understood','basically_understood','partially_understood','not_understood')),
                    value_rating INTEGER NOT NULL CHECK(value_rating BETWEEN 0 AND 3),feeling_tags TEXT,key_learnings TEXT,
                    questions TEXT,next_direction TEXT,created_at TEXT NOT NULL,UNIQUE(module_id,round_id,lesson_no));
                    CREATE TABLE IF NOT EXISTS copilot_background_requests(request_key TEXT PRIMARY KEY,request_hash TEXT NOT NULL,job_id TEXT NOT NULL);''')
                c.execute('''CREATE TABLE IF NOT EXISTS copilot_background_jobs (
                    id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL)''')
                for row in c.execute("SELECT id,data FROM copilot_background_jobs WHERE state IN ('queued','generating')").fetchall():
                    job=json.loads(row['data'])
                    if job.get('worker')!=self.worker:
                        job.update(state='interrupted',error='服务进程已中断，已保留进度；不会自动重新调用模型。',finished_at=now())
                        c.execute('UPDATE copilot_background_jobs SET state=?,data=? WHERE id=?',('interrupted',encoded(job),row['id']))
            self.initialized=True

    @staticmethod
    def public(job):return {k:v for k,v in job.items() if k not in ('worker','request_hash')}

    def get(self,id):
        self.initialize()
        with self.store.conn() as c:row=c.execute('SELECT data FROM copilot_background_jobs WHERE id=?',(id,)).fetchone()
        if not row:fail('not_found','生成任务不存在。',404)
        return self.public(json.loads(row['data']))

    def listing(self):
        self.initialize()
        with self.store.conn() as c:
            order="json_extract(data,'$.created_at')" if isinstance(c,sqlite3.Connection) else "data::jsonb->>'created_at'"
            rows=c.execute('SELECT data FROM copilot_background_jobs ORDER BY '+order+' DESC LIMIT 100').fetchall()
        return [{k:v for k,v in self.public(json.loads(row['data'])).items() if k!='raw'} for row in rows]

    def _create(self,kind,key,values,ai_config):
        self.initialize()
        if kind not in ('summary','advanced'):fail('invalid','不支持的生成类型。',422)
        fingerprint=digest(encoded({'kind':kind,**values}))
        with self.store.lock():
            with self.store.conn() as c:old=c.execute('SELECT request_hash,data FROM copilot_background_jobs WHERE request_key=?',(key,)).fetchone()
            if old:
                if old['request_hash']!=fingerprint:fail('conflict','相同请求标识不能用于不同生成内容。')
                return json.loads(old['data']),None
            with self.store.conn() as c:
                alias=c.execute('SELECT request_hash,job_id FROM copilot_background_requests WHERE request_key=?',(key,)).fetchone()
                if alias:
                    if alias['request_hash']!=fingerprint:fail('conflict','相同请求标识不能用于不同生成内容。')
                    return self.get(alias['job_id']),None
                for row in c.execute("SELECT data FROM copilot_background_jobs WHERE kind=? AND state IN ('queued','generating')",(kind,)).fetchall():
                    running=json.loads(row['data'])
                    if running['request_hash']!=fingerprint:fail('generation_busy','已有同类任务正在生成，请先等待或取消。')
                    c.execute('INSERT INTO copilot_background_requests VALUES (?,?,?)',(key,fingerprint,running['id']))
                    return running,None
            require_config(ai_config)
            # Prompt preparation is read-only; the model starts only in the detached worker.
            job={'id':str(uuid.uuid4()),'kind':kind,'state':'queued','raw':'','phase':'已提交',
                 'created_at':now(),'updated_at':now(),'worker':self.worker,'request_hash':fingerprint,
                 'scope':values.get('scope','full_course'),'result_id':None,'draft_id':None,'error':None}
            with self.store.conn() as c:
                stream=(self.summary.generate('renzhi',1,values.get('scope','full_course'),ai_config=ai_config,persist=False,evidence_resource_id=job['id'],evidence_connection=c)
                        if kind=='summary' else self.summary.generate_advanced(values['summary_content'],ai_config=ai_config,persist=False,evidence_resource_id=job['id'],evidence_connection=c))
                from ai_evidence import linked
                snapshots=linked(c,'course-background',job['id'])
                if snapshots:job['evidence_snapshot_id']=snapshots[0]['id']
                c.execute('INSERT INTO copilot_background_jobs VALUES (?,?,?,?,?,?)',
                          (job['id'],key,fingerprint,kind,'queued',encoded(job)))
                c.execute('INSERT INTO copilot_background_requests VALUES (?,?,?)',(key,fingerprint,job['id']))
            return job,stream

    async def submit(self,kind,key,values,ai_config):
        job,stream=await asyncio.to_thread(self._create,kind,key,values,ai_config)
        if stream is not None:
            task=asyncio.create_task(self.run(job,stream));self.tasks[job['id']]=task
            task.add_done_callback(lambda _:self.tasks.pop(job['id'],None))
        return self.public(job)

    def persist(self,job):
        job['updated_at']=now()
        with self.store.conn() as c:
            c.execute("UPDATE copilot_background_jobs SET state=?,data=? WHERE id=? AND state IN ('queued','generating')",(job['state'],encoded(job),job['id']))

    def complete(self,job,payload):
        job=dict(job)
        content=payload.get('content')
        if not isinstance(content,str) or not content.strip() or len(content)>100000:raise ValueError('Incomplete output')
        # Result and terminal task state commit together; replays never save twice.
        with self.store.conn() as c:
            row=c.execute('SELECT state FROM copilot_background_jobs WHERE id=?',(job['id'],)).fetchone()
            if not row or row['state'] not in ACTIVE:return self.get(job['id'])
            if job['kind']=='summary':
                # 整课复盘沿用生成时的反馈快照；缺失时拒绝保存，不伪造空依据。
                feedback=payload.get('feedback_snapshot')
                if not isinstance(feedback,list):raise ValueError('Missing feedback snapshot')
                row=c.execute('''INSERT INTO copilot_summaries(module_id,round_id,scope,content,feedback_snapshot,created_at)
                    VALUES ('renzhi',1,?,?,?,?) RETURNING id''',(job['scope'],content,encoded(feedback),now())).fetchone()
                job['result_id']=row[0]
                if payload.get('evidence_snapshot_id'):
                    from ai_evidence import bind
                    bind(c,'course-summary',job['result_id'],payload['evidence_snapshot_id'])
            else:
                draft=payload['draft'];number=payload['lesson_no'];job.update(draft_id=job['id'],lesson_no=number)
                c.execute('INSERT INTO copilot_drafts VALUES (?,?,1,?,?,?)',(job['id'],number,'draft',encoded(draft),now()))
                if payload.get('evidence_snapshot_id'):
                    from ai_evidence import bind
                    bind(c,'copilot',job['id'],payload['evidence_snapshot_id'])
            job.update(state='ready',raw=content,phase='已完成并保存',finished_at=now(),updated_at=now())
            c.execute('UPDATE copilot_background_jobs SET state=?,data=? WHERE id=?',('ready',encoded(job),job['id']))
        return job

    async def run(self,job,stream):
        job.update(state='generating',phase='正在生成');last_write=0
        try:
            await asyncio.to_thread(self.persist,dict(job))
            async with asyncio.timeout(300):
                async for block in stream:
                    name=next((line[6:].strip() for line in block.splitlines() if line.startswith('event:')),'')
                    data=json.loads('\n'.join(line[5:].strip() for line in block.splitlines() if line.startswith('data:')))
                    if name=='error':raise ValueError('Provider failed')
                    if name=='complete':
                        commit=asyncio.create_task(asyncio.to_thread(self.complete,dict(job),data))
                        try:result=await asyncio.shield(commit)
                        except asyncio.CancelledError:
                            result=await commit
                            if result['state']!='ready':raise
                        job.update(result);return
                    if data.get('text'):
                        job['raw']+=data['text']
                        if len(job['raw'])>100000:raise ValueError('Oversized output')
                        if time.monotonic()-last_write>=1:
                            await asyncio.to_thread(self.persist,dict(job));last_write=time.monotonic()
            raise ValueError('No completion')
        except asyncio.CancelledError:
            job.update(state='cancelled',error='任务已取消。',finished_at=now())
        except Exception:
            job.update(state='failed',error='生成失败或响应不完整；已保留进度，请核对后显式重试。',finished_at=now())
        finally:
            try:await stream.aclose()
            finally:
                if job['state']!='ready':await asyncio.to_thread(self.persist,dict(job))

    async def cancel(self,id):
        job=await asyncio.to_thread(self.get,id)
        if job['state'] not in ACTIVE:return job
        task=self.tasks.get(id)
        if task:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        job=await asyncio.to_thread(self.get,id)
        if job['state'] in ACTIVE:
            job.update(state='cancelled',error='任务已取消。',finished_at=now());await asyncio.to_thread(self.persist,job)
        return await asyncio.to_thread(self.get,id)

    async def shutdown(self):
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
