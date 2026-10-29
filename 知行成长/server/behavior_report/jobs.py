"""行为报告后台任务：先冻结统计输入，再调用模型；查询恢复不产生模型调用。"""
import asyncio
from datetime import date, datetime, timedelta
import json
import time
import uuid

from copilot.ai_config import require_config
from copilot.core import digest, encoded, fail, now
from ai_evidence import initialize as evidence_schema, freeze, read, bind
from .analyzer import build_prompt
from . import analyzer

ACTIVE = ('queued', 'generating')
TABLES = '''CREATE TABLE IF NOT EXISTS behavior_report_jobs (
    id TEXT PRIMARY KEY,state TEXT NOT NULL,result_id INTEGER,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS behavior_report_requests (
    key TEXT PRIMARY KEY,request_hash TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES behavior_report_jobs(id));
CREATE INDEX IF NOT EXISTS behavior_report_job_states ON behavior_report_jobs(state);'''


class ReportJobs:
    def __init__(self, store):
        self.store = store; self.worker = uuid.uuid4().hex; self.tasks = {}; self.stopping = False

    def initialize(self, c):
        evidence_schema(c)
        for statement in TABLES.split(';'):
            if statement.strip(): c.execute(statement)
        # 重启时只标记中断，保留输出，不重新安排模型调用。
        for row in c.execute("SELECT id FROM behavior_report_jobs WHERE state IN ('queued','generating') AND (data::jsonb->>'worker'<>? OR data::jsonb->>'deadline_at'<=?) ORDER BY id", (self.worker, now())).fetchall():
            self._get(c, row[0])

    def lock(self, c):
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':behavior-report-jobs',0))")

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if k not in ('worker', 'provider_hash')}

    def _get(self, c, job_id):
        row = c.execute('SELECT data FROM behavior_report_jobs WHERE id=? FOR UPDATE', (job_id,)).fetchone()
        if not row: fail('not_found', '报告任务不存在。', 404)
        job = json.loads(row[0])
        if job['state'] in ACTIVE and (job['worker'] != self.worker or job['deadline_at'] <= now()):
            job.update(state='interrupted', error='服务已重启或生成超时，进度已保留；不会自动重新调用模型。', finished_at=now())
            self.put(c, job)
        return job

    def get(self, job_id):
        with self.store.conn() as c: return self.public(self._get(c, job_id))

    def listing(self, page=1, page_size=20):
        with self.store.conn() as c:
            total = c.execute('SELECT count(*) FROM behavior_report_jobs').fetchone()[0]
            ids = [r[0] for r in c.execute("SELECT id FROM behavior_report_jobs ORDER BY (state IN ('queued','generating')) DESC,data::jsonb->>'created_at' DESC,id DESC LIMIT ? OFFSET ?", (page_size, (page-1)*page_size))]
        items = [self.get(jid) for jid in ids]
        return {'items': items, 'total': total, 'page': page, 'page_size': page_size}

    @staticmethod
    def put(c, job):
        job['updated_at'] = now()
        c.execute('INSERT INTO behavior_report_jobs VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,result_id=excluded.result_id,data=excluded.data',
                  (job['id'], job['state'], job.get('result_id'), encoded(job)))

    def prepare(self, key, period_days, ai_config, retry_of=None, deduplicate=True):
        if not isinstance(key, str) or not 8 <= len(key) <= 160: fail('invalid', '报告请求编号无效。', 422)
        if type(period_days) is not int or not 7 <= period_days <= 365: fail('invalid', '分析天数须为7到365。', 422)
        fingerprint = digest(encoded({'period_days': period_days, 'retry_of': retry_of}))
        with self.store.conn() as c:
            self.lock(c)
            previous = c.execute('SELECT request_hash,job_id FROM behavior_report_requests WHERE key=?', (key,)).fetchone()
            if previous:
                if previous[0] != fingerprint: fail('conflict', '相同请求编号不能用于不同分析范围。', 409)
                original = self._get(c, previous[1])
                if ai_config is not None:
                    supplied = require_config(ai_config)
                    provider = digest(encoded({'url': supplied['url'], 'model': supplied['model']}))
                    if provider != original['provider_hash']:
                        fail('conflict', '相同请求编号不能更换分析模型或服务地址。', 409)
                return original, None
            cfg = require_config(ai_config)
            provider = digest(encoded({'url': cfg['url'], 'model': cfg['model']}))
            from growth_statistics import shanghai_today
            day = shanghai_today().isoformat()
            original = None
            if retry_of:
                original = self._get(c, retry_of)
                if original['state'] not in ('interrupted', 'failed', 'cancelled') or original['period_days'] != period_days:
                    fail('conflict', '只有未完成任务可以重试原输入，请核对分析范围。', 409)
                day = original['scope_day']
            for row in c.execute("SELECT id FROM behavior_report_jobs WHERE state IN ('queued','generating')").fetchall():
                old = self._get(c, row[0])
                if deduplicate and old['state'] in ACTIVE and old['period_days'] == period_days and old['scope_day'] == day and old.get('retry_of') == retry_of and old['provider_hash'] == provider:
                    c.execute('INSERT INTO behavior_report_requests VALUES (?,?,?)', (key, fingerprint, old['id']))
                    return old, None
            jid = 'behavior-' + uuid.uuid4().hex
            if retry_of:
                before = read(c, original['evidence_snapshot_id'])
                snapshot = freeze(c, 'behavior-report', jid, before['messages'], cfg['model'],
                    sources=before['sources'], prompt_version=before['prompt_version'], parent_id=before['id'], selection=before['selection'])
                summary = original['data_summary']; day = original['scope_day']
            else:
                summary = analyzer.collect_data_summary(self.store.db_path, period_days, end_day=date.fromisoformat(day))
                selection = {'period_days': period_days, 'business_date': day, 'period': summary.get('period'), 'scope': '仅统计摘要，不含私人原文',
                    'source_sets': ['本人学习完成记录与手工打卡','手工习惯记录','课程学习计时','行动确认记录','行为应用','错误记录','预测','日常记录与旧四问复盘'],
                    'count_rules': ['北京时间内按日与模块合并学习完成/打卡，同模块同日只计一次。',
                        '手工分钟、课程秒数、行动确认分钟各自统计，可能重叠，不相加。',
                        '预测准确率只使用已揭晓记录；复盘按未归档的当前记录身份计数，编辑与AI版本不额外计数。',
                        '行为概念、错误类型只列出现次数最多的前5项；未比较前一时段，不证明长期趋势。']}
                from ai_evidence import source
                sources = [source('aggregate', name, '本期统计 · ' + name, value, date=day, scope='统计摘要与计数口径',
                    origin={'kind':'behavior-summary','period_days':period_days,'business_day':day,'field':name}) for name, value in summary.items() if name != 'period']
                snapshot = freeze(c, 'behavior-report', jid, [{'role': 'user', 'content': build_prompt(summary)}],
                    cfg['model'], sources=sources, prompt_version='behavior-report-evidence-v1', selection=selection)
            job = {'id': jid, 'kind': 'behavior-report', 'state': 'queued', 'raw': '', 'phase': '已冻结分析依据',
                   'created_at': now(), 'worker': self.worker, 'deadline_at': (datetime.fromisoformat(now()) + timedelta(seconds=180)).isoformat(),
                   'scope_day': day, 'period_days': period_days, 'retry_of': retry_of, 'data_summary': summary,
                   'evidence_snapshot_id': snapshot['id'], 'model': cfg['model'], 'provider_hash': provider, 'result_id': None, 'error': None}
            self.put(c, job)
            c.execute('INSERT INTO behavior_report_requests VALUES (?,?,?)', (key, fingerprint, jid))
            return job, cfg

    async def submit(self, key, period_days, ai_config, retry_of=None, *, deduplicate=True, commit_gate=None):
        job, cfg = await asyncio.to_thread(self.prepare, key, period_days, ai_config, retry_of, deduplicate)
        if cfg is not None:
            task = asyncio.create_task(self.run(job, cfg, commit_gate)); self.tasks[job['id']] = task
            task.add_done_callback(lambda _: self.tasks.pop(job['id'], None))
        return self.public(job)

    def progress(self, job):
        with self.store.conn() as c:
            current = self._get(c, job['id'])
            if current['state'] not in ACTIVE:
                # 取消后补存最后一秒内已接收的输出，只补正文，不反转终态或结果引用。
                if current['state'] in ('cancelled','interrupted') and len(job['raw']) > len(current['raw']):
                    current['raw']=job['raw'];self.put(c,current)
                return False
            self.put(c, job); return True

    def complete(self, job):
        from growth_statistics import shanghai_today
        with self.store.conn() as c:
            current = self._get(c, job['id'])
            if current['state'] not in ACTIVE: return current
            row = c.execute('INSERT INTO behavior_reports(date,period_days,content,data_summary) VALUES (?,?,?,?) RETURNING id',
                (shanghai_today().isoformat(), job['period_days'], job['raw'].strip(), encoded(job['data_summary']))).fetchone()
            bind(c, 'behavior-result', row[0], job['evidence_snapshot_id'])
            job.update(state='ready', phase='报告已生成并保存', result_id=row[0], finished_at=now())
            self.put(c, job); return job

    async def run(self, job, cfg, commit_gate=None):
        from copilot.transport import qwen_stream
        try:
            job.update(state='generating', phase='正在分析冻结的统计摘要')
            if not await asyncio.to_thread(self.progress, job): return
            from ai_evidence import messages
            prompt = await asyncio.to_thread(messages, self.store.conn, job['evidence_snapshot_id'])
            complete = False; checkpoint = 0
            async with asyncio.timeout(180):
                async for packet in qwen_stream(prompt, cfg):
                    job['raw'] += packet.get('text', '')
                    if len(job['raw']) > 40000: raise ValueError('Oversized report')
                    complete = complete or bool(packet.get('done'))
                    if time.monotonic()-checkpoint >= 1:
                        if not await asyncio.to_thread(self.progress, job): return
                        checkpoint = time.monotonic()
                if not complete or not job['raw'].strip(): raise ValueError('Incomplete report')
            if commit_gate is not None:
                # 旧等待接口在完整输出后确认连接仍在，才沿用同一个保存事务。
                job.update(awaiting_confirmation=True,phase='等待原请求确认保存')
                if not await asyncio.to_thread(self.progress,job):return
                remaining=(datetime.fromisoformat(job['deadline_at'])-datetime.fromisoformat(now())).total_seconds()
                async with asyncio.timeout(max(0,remaining)):await commit_gate.wait()
                job['awaiting_confirmation']=False
            commit = asyncio.create_task(asyncio.to_thread(self.complete, job))
            try: job.update(await asyncio.shield(commit))
            except asyncio.CancelledError:
                job.update(await commit)
                if job['state'] != 'ready': raise
        except asyncio.CancelledError:
            job.update(state='interrupted' if self.stopping else 'cancelled', error='调用已中断，进度保留，未自动重试。', finished_at=now())
            await asyncio.to_thread(self.progress, job)
        except Exception:
            job.update(state='failed', error='报告生成或保存未完成，已保留进度；请核对后手动重试。', finished_at=now())
            await asyncio.to_thread(self.progress, job)
        finally:
            cfg.clear()

    async def cancel(self, job_id):
        def mark():
            with self.store.conn() as c:
                job = self._get(c, job_id)
                if job['state'] in ACTIVE:
                    job.update(state='cancelled', error='本人取消生成。', finished_at=now()); self.put(c, job)
                return job
        job = await asyncio.to_thread(mark)
        task = self.tasks.get(job_id)
        if task and job['state'] == 'cancelled':
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        return await asyncio.to_thread(self.get, job_id)

    async def shutdown(self):
        self.stopping = True
        tasks = list(self.tasks.values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
