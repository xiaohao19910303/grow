"""浏览器投资执行交接：远端只冻结输入、校验引用并归档，不计算筛选或调用模型。"""
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from functools import wraps

import db
from pydantic import Field, StringConstraints, model_validator
from ai_evidence import freeze, inputs, read
from copilot.core import digest, encoded, fail, now
from .contracts import Contract
from .screening import ScreenInput
from .analysis import validate_report
from history_sources import record_source

ALGORITHM = 'browser-screen-rational-v1'


def storage_operation(function):
    @wraps(function)
    def call(*args, **kwargs):
        try: return function(*args, **kwargs)
        except db.psycopg2.Error:
            fail('local_storage', '远端保存未确认；请保留本机检查点，以相同请求重试。', 503)
    return call


class BrowserRunInput(Contract):
    account_id: str = Field(min_length=1, max_length=100)
    instrument_ids: list[str] = Field(min_length=1, max_length=20)
    screen: ScreenInput
    model: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    executor: str = Field(min_length=16, max_length=100, repr=False)

    @model_validator(mode='after')
    def valid(self):
        if len(set(self.instrument_ids)) != len(self.instrument_ids) or self.screen.limit > 5:
            raise ValueError('最多评估前5个候选，标的不能重复。')
        if not self.model.strip() or any(ord(c) < 32 for c in self.model):
            raise ValueError('模型名称无效。')
        return self


class Candidate(Contract):
    instrument_id: str = Field(min_length=1, max_length=100)
    data_date: date
    values: dict
    condition_results: list[bool | None] = Field(max_length=10)


class BrowserScreenResult(Contract):
    algorithm: Literal['browser-screen-rational-v1']
    input_hash: str = Field(min_length=64, max_length=64)
    executor: str = Field(min_length=16, max_length=100, repr=False)
    items: list[Candidate] = Field(max_length=5)
    total: int = Field(ge=0, le=20)
    unresolved: int = Field(ge=0, le=20)


class BrowserOwner(Contract):
    executor: str = Field(min_length=16, max_length=100, repr=False)


class BrowserOutput(BrowserOwner):
    input_hash: str = Field(min_length=64, max_length=64)
    raw: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=80000, repr=False)


class BrowserPause(BrowserOwner):
    status: Literal['call_uncertain', 'waiting_upload']


class BrowserExecution:
    def __init__(self, store, analysis):
        self.store, self.analysis = store, analysis

    def initialize(self, c):
        if not c.execute("SELECT to_regclass('investment_local_runs')").fetchone()[0]:
            c.execute('CREATE TABLE investment_local_runs (id TEXT PRIMARY KEY,data TEXT NOT NULL)')

    @staticmethod
    def public(run):
        return {k: v for k, v in run.items() if k not in ('owner_hash', 'research', 'research_sources')}

    def summary(self, c, run):
        result = self.public(run)
        jobs = {iid: self.job_in(c, jid) for iid, jid in run['jobs'].items()}
        result['job_states'] = {iid: job['state'] for iid, job in jobs.items()}
        states = list(result['job_states'].values())
        if run['state'] != 'cancelled' and run.get('screening'):
            count = len(run['screening']['items'])
            if len(states) == count and all(s == 'ready' for s in states): result['state'] = 'ready'
            elif any(s in ('failed', 'cancelled', 'interrupted') for s in states) or any(j.get('local_status') for j in jobs.values()): result['state'] = 'partial'
        return result

    @staticmethod
    def owner(value, executor):
        if value.get('owner_hash') != digest(executor):
            fail('local_owner', '此任务由另一个浏览器领取；请在原浏览器恢复，或取消后新建。')

    @staticmethod
    def put(c, run):
        c.execute('UPDATE investment_local_runs SET data=? WHERE id=?', (encoded(run), run['id']))

    def get_in(self, c, run_id):
        self.initialize(c)
        row = c.execute('SELECT data FROM investment_local_runs WHERE id=?', (run_id,)).fetchone()
        if not row: fail('not_found', '本地筛选批次不存在。', 404)
        return json.loads(row[0])

    @storage_operation
    def create(self, request, key):
        payload = request.model_dump(mode='json')
        fingerprint = digest(encoded({'browser_run': payload}))
        with db.connect() as c:
            self.store.lock(c);self.initialize(c)
            old = self.store.replay(c, key, fingerprint)
            if old is not None: return old
            self.store._get(c, 'accounts', request.account_id)
            universe = [];sources = []
            for instrument_id in request.instrument_ids:
                instrument = self.store._get(c, 'instruments', instrument_id)
                if instrument['kind'] == 'fund': fail('invalid_scope', '此入口仅筛选股票和场内ETF。', 422)
                row = c.execute("""SELECT data FROM investment_objects WHERE kind='market-snapshots'
                    AND data::jsonb->>'instrument_id'=? ORDER BY created_at DESC,id DESC LIMIT 1""", (instrument_id,)).fetchone()
                market = json.loads(row[0]) if row else {}
                for original in (instrument, market):
                    if original:
                        sources.append(record_source(c, 'investment_objects', (original['id'],), instrument['name'],
                            original, fields=['data'], target={'kind':'investment','id':original['id'],
                                'resource':'instruments' if original['id']==instrument_id else 'market-snapshots','account_id':request.account_id}))
                bars = market.get('bars', [])
                if len(bars) > 200: fail('local_scope', '单个标的超过200条日线，请缩小输入范围。', 422)
                universe.append({**{k: instrument[k] for k in ('id', 'name', 'code', 'market', 'kind')},
                    'instrument_id': instrument_id, 'bars': bars, 'snapshot_id': market.get('id'),
                    'provider': market.get('provider'), 'retrieved_at': market.get('retrieved_at')})
            run_id = 'local-run-' + uuid.uuid4().hex
            bundle = {'universe': universe, 'request': request.screen.model_dump(mode='json'), 'algorithm': ALGORITHM}
            evidence = freeze(c, 'investments', run_id, [{'role': 'user', 'content': encoded(bundle)}], request.model,
                sources=[*inputs(bundle, '本人选择的行情缓存；仅浏览器计算'), *sources], prompt_version=ALGORITHM,
                stage='screening', selection={'execution_location': 'browser', 'computational_input': True,
                    'period': request.screen.as_of.isoformat(), 'scope':'仅为本批次规则计算输入；候选模型分析另有独立快照，平台不调用模型。'})
            run = {'id': run_id, 'state': 'awaiting_browser', 'created_at': now(), 'account_id': request.account_id,
                'input_snapshot_id': evidence['id'], 'input_hash': evidence['input_hash'], 'algorithm': ALGORITHM, 'protocol_version': 1,
                'model': request.model, 'question': request.question, 'owner_hash': digest(request.executor),
                'jobs': {}, 'research': {}, 'research_sources': {}, 'full_market': False, 'execution_location': 'browser'}
            c.execute('INSERT INTO investment_local_runs VALUES (?,?)', (run_id, encoded(run)))
            result = self.public(run);self.store.remember(c, key, fingerprint, result)
            return result

    @storage_operation
    def get(self, run_id, include_input=False):
        with db.connect() as c:
            self.store.lock(c)
            run = self.get_in(c, run_id);result = self.summary(c, run)
            if include_input:
                result['bundle'] = json.loads(read(c, run['input_snapshot_id'])['messages'][0]['content'])
            return result

    @storage_operation
    def listing(self, page):
        with db.connect() as c:
            self.store.lock(c);self.initialize(c)
            rows = c.execute("SELECT data FROM investment_local_runs ORDER BY data::jsonb->>'created_at' DESC,id DESC LIMIT 20 OFFSET ?", ((page - 1) * 20,))
            return {'items': [self.summary(c, json.loads(r[0])) for r in rows], 'page': page,
                    'total': c.execute('SELECT COUNT(*) FROM investment_local_runs').fetchone()[0]}

    @storage_operation
    def screen_result(self, run_id, request, key):
        fingerprint = digest(encoded({'browser_screen': run_id, 'data': request.model_dump(mode='json')}))
        with db.connect() as c:
            self.store.lock(c)
            old = self.store.replay(c, key, fingerprint)
            if old is not None: return old
            run = self.get_in(c, run_id);self.owner(run, request.executor)
            if run['state'] != 'awaiting_browser' or run['input_hash'] != request.input_hash:
                fail('local_state', '批次状态或输入不匹配，请查询原保存结果。')
            bundle = json.loads(read(c, run['input_snapshot_id'])['messages'][0]['content'])
            universe = {i['instrument_id']: i for i in bundle['universe']}
            if request.total + request.unresolved > len(universe) or len(request.items) != min(request.total, bundle['request']['limit']):
                fail('invalid_result', '候选数量与批次范围不匹配。', 422)
            seen = set()
            for candidate in request.items:
                iid = candidate.instrument_id
                if iid not in universe or iid in seen: fail('invalid_result', '候选身份无效或重复。', 422)
                seen.add(iid);source = universe[iid]
                bars = [b for b in source['bars'] if b['date'] <= bundle['request']['as_of']]
                values = candidate.values
                fields = {'market', 'kind', 'name', 'close', 'close_change_pct', 'turnover_cny', 'volume_ratio_5', 'price_above_ma20'}
                if set(values) != fields or len(candidate.condition_results) != len(bundle['request']['conditions']) or not bars or candidate.data_date.isoformat() != bars[-1]['date']:
                    fail('invalid_result', '筛选字段、条件或行情日期不匹配。', 422)
                if any(values[k] != source[k] for k in ('market', 'kind', 'name')) or values['close'] != bars[-1]['close'] or values['turnover_cny'] != bars[-1]['turnover_cny']:
                    fail('invalid_result', '基础行情与冻结来源不匹配。', 422)
                for k in ('close_change_pct', 'volume_ratio_5'):
                    v = values[k]
                    try:
                        if v is not None and (not isinstance(v, str) or len(v) > 100 or not Decimal(v).is_finite()): raise ValueError()
                    except (ValueError, ArithmeticError): fail('invalid_result', '本地指标格式无效。', 422)
                if values['price_above_ma20'] is not None and type(values['price_above_ma20']) is not bool:
                    fail('invalid_result', '均线条件格式无效。', 422)
                content = encoded({'execution_location': 'browser', 'calculation_verification': 'client_reported',
                    'algorithm': ALGORITHM, 'input_snapshot_id': run['input_snapshot_id'],
                    'instrument': {k: source[k] for k in ('name', 'code', 'market', 'kind')},
                    'screen_values': values, 'conditions': bundle['request'], 'condition_results': candidate.condition_results,
                    'bars': bars[-20:], 'stored_bar_count': len(bars), 'summary_omitted_bar_count': max(0, len(bars) - 20),
                    'limitations': ['本人选择的缓存行情，非全市场或历史时点回测。', '指标为浏览器计算自报，远端未重算；来源真实性未独立核验。']})
                record = self.store.create_in(c, 'research', self.store.validate('research', {
                    'instrument_id': iid, 'account_id': run['account_id'], 'title': source['name'] + ' · 浏览器筛选摘要',
                    'content': content, 'available_at': now(), 'locator': '批次 ' + run_id,
                    'contrary_evidence': '日线未复权口径、来源完整性、公告及基本面尚需核对。'}), 'browser-research-' + digest(run_id + iid))
                run['research'][iid] = record
                run['research_sources'][iid] = record_source(c, 'investment_objects', (record['id'],), record['title'],
                    record, fields=['data'], target={'kind':'investment','id':record['id'],'resource':'research','account_id':run['account_id']})
            run['screening'] = request.model_dump(mode='json', exclude={'executor'})
            for item in run['screening']['items']:
                item['code'] = universe[item['instrument_id']]['code']
            run['state'] = 'screened' if request.items else 'ready';self.put(c, run)
            result = self.public(run);self.store.remember(c, key, fingerprint, result)
            return result

    @staticmethod
    def job_in(c, job_id):
        row = c.execute('SELECT data FROM investment_analysis_jobs WHERE id=?', (job_id,)).fetchone()
        if not row: fail('not_found', '分析任务不存在。', 404)
        return json.loads(row[0])

    @storage_operation
    def start_candidate(self, run_id, instrument_id, request, key):
        self.analysis.initialize()
        fingerprint = digest(encoded({'browser_candidate': run_id, 'instrument': instrument_id, 'owner': digest(request.executor)}))
        with db.connect() as c:
            self.store.lock(c)
            old = self.store.replay(c, key, fingerprint)
            if old is not None: return old
            run = self.get_in(c, run_id);self.owner(run, request.executor)
            if run['state'] == 'cancelled' or instrument_id not in run['research']:
                fail('local_state', '批次已取消或此标的未被选中。')
            if run.get('protocol_version')==2 and instrument_id not in run.get('analysis_selection',[]):
                fail('invalid_selection','请先选择并冻结需要AI研究的候选。',422)
            if instrument_id in run['jobs']:
                result = self.analysis.public(self.job_in(c, run['jobs'][instrument_id]))
                self.store.remember(c, key, fingerprint, result)
                return result
            bundle = json.loads(read(c, run['input_snapshot_id'])['messages'][0]['content'])
            instrument = next(i for i in bundle['universe'] if i['instrument_id'] == instrument_id)
            selected = run['research'][instrument_id]
            snapshot = {'kind': 'research', 'question': run['question'], 'decision_at': now(), 'instrument_id': instrument_id,
                'instrument': {k: instrument[k] for k in ('id', 'name', 'code', 'market', 'kind')},
                'evidence': [selected], 'plans': [], 'reviews': [], 'policies': [], 'dossiers': [], 'campaigns': [],
                'prompt_version': 'investment-v5', 'include_amounts': False, 'mode': 'browser_screen',
                'limitations': ['仅选定缓存行情和浏览器筛选摘要；未发送私人笔记、交易与账户金额。', '本地自报执行，远端仅校验结构及引用。']}
            stamp = now();preview_id = 'preview-' + uuid.uuid4().hex;job_id = 'analysis-' + uuid.uuid4().hex
            preview = {'id': preview_id, 'version': 1, 'created_at': stamp, 'updated_at': stamp,
                       'snapshot': snapshot, 'snapshot_hash': digest(encoded(snapshot)), 'account_id': run['account_id']}
            self.store.save(c, 'analysis-previews', preview, fresh=True)
            origins = read(c, run['input_snapshot_id'])['sources']
            keys = {instrument_id, instrument.get('snapshot_id')}
            origins = [s for s in origins if (s.get('origin') or {}).get('keys', [None])[0] in keys]
            for source in origins:
                if (source.get('origin') or {}).get('keys') == [instrument.get('snapshot_id')]:
                    source['truncated'] = json.loads(selected['content'])['summary_omitted_bar_count'] > 0
                    source['scope'] = '规则使用冻结日线；模型仅收到截至筛选日期的最近20条及本地计算摘要。'
            evidence = freeze(c, 'investments', job_id, self.analysis.evidence_messages(snapshot), run['model'],
                sources=[*inputs(snapshot), *origins, run['research_sources'][instrument_id]],
                prompt_version='investment-v5', stage='analysis', parent_id=run['input_snapshot_id'],
                selection={'scope':'浏览器将实际发送给本人模型的选定行情及筛选摘要；不含交易和账户金额。'})
            job = {'id': job_id, 'state': 'queued', 'phase': '等待原浏览器直接调用模型', 'created_at': stamp,
                'updated_at': stamp, 'preview_id': preview_id, 'snapshot_hash': preview['snapshot_hash'], 'model': run['model'],
                'prompt_version': 'investment-v5', 'same_model_review': True, 'execution_location': 'browser',
                'local_run_id': run_id, 'local_instrument_id': instrument_id, 'owner_hash': run['owner_hash'],
                'evidence_snapshot_id': evidence['id'], 'fingerprint': fingerprint}
            c.execute('INSERT INTO investment_analysis_jobs VALUES (?,?,?,?)', (job_id, 'queued', fingerprint, encoded(job)))
            run['jobs'][instrument_id] = job_id;self.put(c, run)
            result = self.analysis.public(job);self.store.remember(c, key, fingerprint, result)
            return result

    @storage_operation
    def job_input(self, job_id, executor):
        with db.connect() as c:
            job = self.job_in(c, job_id);self.owner(job, executor)
            if job.get('execution_location') != 'browser' or job['state'] not in ('queued', 'running'):
                fail('local_state', '此任务不能继续进行浏览器模型调用。')
            stage = 'countercheck' if job.get('counter_snapshot_id') else 'analysis'
            evidence = read(c, job.get('counter_snapshot_id') or job['evidence_snapshot_id'])
            return {'job': self.analysis.public(job), 'stage': stage, 'evidence': evidence}

    @storage_operation
    def output(self, job_id, stage, request, key):
        fingerprint = digest(encoded({'browser_output': job_id, 'stage': stage, 'data': request.model_dump(mode='json')}))
        with db.connect() as c:
            self.store.lock(c)
            old = self.store.replay(c, key, fingerprint)
            if old is not None: return old
            job = self.job_in(c, job_id);self.owner(job, request.executor)
            if job.get('execution_location') != 'browser' or job['state'] not in ('queued', 'running'):
                fail('local_state', '任务已结束或取消，不能接收迟到结果。')
            expected = job['evidence_snapshot_id'] if stage == 'draft' else job.get('counter_snapshot_id')
            if not expected or read(c, expected)['input_hash'] != request.input_hash or (stage == 'draft' and job.get('counter_snapshot_id')):
                fail('local_state', '模型阶段或输入哈希不匹配，请查询原回执。')
            preview = self.store._get(c, 'analysis-previews', job['preview_id'])
            try: report = validate_report(request.raw, preview['snapshot'], check_conditions=stage == 'result')
            except ValueError: fail('invalid_report', '模型输出未通过结构、原文引用或条件检查；本机输出仍保留。', 422)
            if stage == 'draft':
                evidence = freeze(c, 'investments', job_id, self.analysis.evidence_messages(preview['snapshot'], draft=report), job['model'],
                    sources=read(c, job['evidence_snapshot_id'])['sources'], prompt_version=job['prompt_version'],
                    stage='countercheck', parent_id=job['evidence_snapshot_id'],
                    selection={'scope':'浏览器将实际发送的反证消息，包含已接收初稿；仍由同一模型处理。'})
                job.update(state='running', phase='等待原浏览器反证', draft_report=report,
                           draft_raw=request.raw, counter_snapshot_id=evidence['id'])
            else:
                job.update(state='ready', phase='浏览器评估已保存；等待本人核对', report=report, result_raw=request.raw,
                           validation_note='本地自报执行；远端通过结构、逐字引用及条件检查，未重算筛选或核验行情真实性。')
            job['updated_at'] = now()
            job.pop('local_status', None)
            c.execute('UPDATE investment_analysis_jobs SET state=?,data=? WHERE id=?', (job['state'], encoded(job), job_id))
            run = self.get_in(c, job['local_run_id'])
            jobs = [self.job_in(c, jid) for jid in run['jobs'].values()]
            statuses = [j['state'] for j in jobs]
            count=len(run.get('analysis_selection',[])) if run.get('protocol_version')==2 else len(run['screening']['items'])
            run['state'] = 'ready' if len(statuses) == count and all(s == 'ready' for s in statuses) else 'running'
            if any(s in ('failed', 'interrupted', 'cancelled') for s in statuses) or any(j.get('local_status') for j in jobs): run['state'] = 'partial'
            self.put(c, run)
            result = self.analysis.public(job);self.store.remember(c, key, fingerprint, result)
            return result

    @storage_operation
    def pause(self, job_id, request):
        with db.connect() as c:
            self.store.lock(c);job = self.job_in(c, job_id);self.owner(job, request.executor)
            if job.get('execution_location') != 'browser': fail('local_state', '不是浏览器执行任务。')
            if job['state'] in ('queued', 'running'):
                job['local_status'] = request.status
                job['phase'] = '浏览器模型调用结果未确认，不自动重试' if request.status == 'call_uncertain' else '浏览器输出待确认上传'
                if request.status == 'call_uncertain': job['state'] = 'interrupted'
                job['updated_at'] = now()
                c.execute('UPDATE investment_analysis_jobs SET state=?,data=? WHERE id=?', (job['state'], encoded(job), job_id))
                run = self.get_in(c, job['local_run_id'])
                if run['state'] != 'cancelled': run['state'] = 'partial';self.put(c, run)
            return self.analysis.public(job)

    @storage_operation
    def cancel(self, run_id):
        with db.connect() as c:
            self.store.lock(c);run = self.get_in(c, run_id)
            run['state'] = 'cancelled';self.put(c, run)
            for job_id in run['jobs'].values():
                job = self.job_in(c, job_id)
                if job['state'] in ('queued', 'running'):
                    job.update(state='cancelled', phase='本人取消浏览器批次', updated_at=now())
                    c.execute('UPDATE investment_analysis_jobs SET state=?,data=? WHERE id=?', ('cancelled', encoded(job), job_id))
            return self.public(run)
