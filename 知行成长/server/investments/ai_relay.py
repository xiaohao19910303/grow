"""Explicit, private relay for browser investment calls, with replay-safe receipts."""
import asyncio
import json
import os
from urllib.parse import urlsplit

import db
from fastapi import Header, Request
from pydantic import Field, StrictBool, model_validator

from ai_evidence import freeze, inputs, read
from copilot.ai_config import require_config
from copilot.core import digest, encoded, fail, now
from .contracts import Contract, Identifier
from .bounded_http import public_addresses,PinnedTransport

TABLES='''CREATE TABLE IF NOT EXISTS investment_relay_calls (
    request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
    state TEXT NOT NULL, data TEXT NOT NULL);'''
DEFAULT_HOSTS='ark.cn-beijing.volces.com,api.openai.com,api.deepseek.com,dashscope.aliyuncs.com'


def allowed_hosts():
    return sorted({h.strip().lower() for h in os.getenv('INVESTMENT_AI_RELAY_HOSTS',DEFAULT_HOSTS).split(',')
                   if h.strip() and '*' not in h and '/' not in h and ':' not in h})


class RelayInput(Contract):
    account_id: Identifier
    purpose: str = Field(pattern=r'^(parse|candidate)$')
    messages: list[dict] = Field(default_factory=list,max_length=4,repr=False)
    ai_config: dict = Field(repr=False)
    consent: StrictBool
    job_id: Identifier | None = None
    executor: str | None = Field(default=None,min_length=16,max_length=100,repr=False)
    input_hash: str | None = Field(default=None,pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def confirmed(self):
        if not self.consent:raise ValueError('请明确选择本次转发。')
        if self.purpose=='candidate' and not all((self.job_id,self.executor,self.input_hash)):
            raise ValueError('候选调用须绑定冻结输入。')
        if self.purpose=='parse':
            if not self.messages or len(encoded(self.messages).encode())>80000:raise ValueError('解析输入无效。')
            for message in self.messages:
                if set(message)!={'role','content'} or message['role'] not in ('system','user') or not isinstance(message['content'],str):
                    raise ValueError('仅接收选股解析正文。')
        elif self.messages:raise ValueError('候选消息由冻结证据读取。')
        return self


def destination(url):
    return public_addresses(url,allowed_hosts())


class InvestmentRelay:
    def __init__(self,store,browser):self.store=store;self.browser=browser

    def prepare(self,payload,key,cfg):
        fingerprint=digest(encoded({'account_id':payload.account_id,'purpose':payload.purpose,'messages':payload.messages,
            'url':cfg['url'],'model':cfg['model'],'job_id':payload.job_id,'input_hash':payload.input_hash,
            'executor_hash':digest(payload.executor or '')}))
        with db.connect() as c:
            self.store.lock(c);c.executescript(TABLES);self.store._get(c,'accounts',payload.account_id)
            old=c.execute('SELECT fingerprint,state,data FROM investment_relay_calls WHERE request_key=?',(key,)).fetchone()
            if old:
                if old[0]!=fingerprint:fail('relay_conflict','同一调用编号不能更换发送内容或目的地。',409)
                if old[1]=='ready':return json.loads(old[2]),None
                fail('relay_uncertain','原调用结果未确认，不会再次请求模型；请核对后新建尝试。',409)
        cfg['_addresses']=destination(cfg['url'])
        messages=payload.messages
        if payload.purpose=='candidate':
            selected=self.browser.job_input(payload.job_id,payload.executor)
            if selected['evidence']['input_hash']!=payload.input_hash or selected['evidence']['model']!=cfg['model']:
                fail('relay_input','模型或冻结输入与候选任务不同。',409)
            with db.connect() as c:
                run=self.browser.get_in(c,selected['job']['local_run_id'])
                if run['account_id']!=payload.account_id:fail('relay_scope','候选不属于当前投资账户。',422)
            messages=selected['evidence']['messages']
        with db.connect() as c:
            self.store.lock(c);c.executescript(TABLES);self.store._get(c,'accounts',payload.account_id)
            old=c.execute('SELECT fingerprint,state,data FROM investment_relay_calls WHERE request_key=?',(key,)).fetchone()
            if old:
                if old[0]!=fingerprint:fail('relay_conflict','同一调用编号不能更换发送内容或目的地。',409)
                if old[1]=='ready':return json.loads(old[2]),None
                fail('relay_uncertain','原调用结果未确认，不会再次请求模型；请核对后新建尝试。',409)
            snapshot=freeze(c,'investments','relay-'+digest(key),messages,cfg['model'],
                sources=inputs({'purpose':payload.purpose,'messages':messages},'本人确认的转发范围'),
                prompt_version='investment-relay-v1',stage='relay')
            data={'state':'started','account_id':payload.account_id,'created_at':now(),
                  'purpose':payload.purpose,'job_id':payload.job_id,
                  'evidence_snapshot_id':snapshot['id'],'input_hash':snapshot['input_hash'],'destination_host':urlsplit(cfg['url']).hostname}
            c.execute('INSERT INTO investment_relay_calls VALUES (?,?,?,?)',(key,fingerprint,'started',encoded(data)))
        return data,messages

    def finish(self,key,data,state):
        with db.connect() as c:
            self.store.lock(c)
            c.execute("UPDATE investment_relay_calls SET state=?,data=? WHERE request_key=? AND (state<>'ready' OR ?='ready')",(state,encoded(data),key,state))
            return json.loads(c.execute('SELECT data FROM investment_relay_calls WHERE request_key=?',(key,)).fetchone()[0])

    def resume(self,job_id,executor,call_key):
        with db.connect() as c:
            self.store.lock(c);job=self.browser.job_in(c,job_id);self.browser.owner(job,executor)
            run=self.browser.get_in(c,job['local_run_id'])
            row=c.execute("SELECT data FROM investment_relay_calls WHERE request_key=? AND state='ready'",(call_key,)).fetchone()
            if not row:fail('relay_uncertain','原调用没有已完成回执，未恢复任务。',409)
            receipt=json.loads(row[0]);expected=job.get('counter_snapshot_id') or job['evidence_snapshot_id']
            if run['state']=='cancelled' or job['state']=='cancelled' or receipt.get('purpose')!='candidate' or receipt.get('job_id')!=job_id or receipt['account_id']!=run['account_id'] or receipt['input_hash']!=read(c,expected)['input_hash']:
                fail('relay_scope','回执不属于当前阶段，或原批次已取消。',409)
            if job['state']=='interrupted' and job.get('local_status')=='call_uncertain':
                job.update(state='running' if job.get('counter_snapshot_id') else 'queued',phase='已找回转发回执，等待归档')
                c.execute('UPDATE investment_analysis_jobs SET state=?,data=? WHERE id=?',(job['state'],encoded(job),job_id))
            return receipt

    async def call(self,payload,key,request):
        cfg=require_config(payload.ai_config)
        try:
            receipt,messages=await asyncio.to_thread(self.prepare,payload,key,cfg)
            if messages is None:return receipt
            cfg['_transport']=PinnedTransport(cfg['url'],cfg['_addresses'])
            from copilot.transport import qwen_stream
            raw='';complete=False
            try:
                async with asyncio.timeout(180):
                    async for packet in qwen_stream(messages,cfg):
                        if await request.is_disconnected():raise asyncio.CancelledError()
                        raw+=packet.get('text','')
                        if len(raw)>80000:raise ValueError('Oversized output')
                        complete=complete or bool(packet.get('done'))
                if not complete or not raw.strip():raise ValueError('Incomplete output')
                receipt.update(state='ready',raw=raw,finished_at=now())
                saving=asyncio.create_task(asyncio.to_thread(self.finish,key,receipt,'ready'))
                try:receipt=await asyncio.shield(saving)
                except asyncio.CancelledError:
                    await saving
                    raise
                return receipt
            except (Exception,asyncio.CancelledError) as error:
                receipt.update(state='uncertain',finished_at=now())
                await asyncio.shield(asyncio.to_thread(self.finish,key,receipt,'uncertain'))
                if isinstance(error,asyncio.CancelledError):raise
                fail('relay_uncertain','模型调用或保存结果未确认；不会自动重发，请核对原任务。',502)
        finally:
            cfg.clear();payload.ai_config.clear()


def register(router,store,browser):
    relay=InvestmentRelay(store,browser)
    @router.get('/ai-relay/config')
    def relay_config():return {'hosts':allowed_hosts(),'explicit_consent_required':True,'automatic_fallback':False}

    @router.get('/ai-relay/calls/{call_key}')
    def relay_receipt(call_key:str):
        with db.connect() as c:
            c.executescript(TABLES)
            row=c.execute('SELECT state,data FROM investment_relay_calls WHERE request_key=?',(call_key,)).fetchone()
            if not row:fail('not_found','转发回执不存在。',404)
            result=json.loads(row[1])
            if row[0]!='ready':fail('relay_uncertain','原调用未确认，不会重新调用模型。',409)
            return result

    @router.post('/ai-relay')
    async def relay_call(payload:RelayInput,request:Request,idempotency_key:str=Header(min_length=8,max_length=160)):
        origin=f'{request.url.scheme}://{request.url.netloc}'
        if request.headers.get('Origin',origin)!=origin or request.headers.get('Sec-Fetch-Site')=='cross-site':
            fail('same_origin_required','仅允许本人在当前站点明确发起转发。',403)
        return await relay.call(payload,idempotency_key,request)

    class ResumeInput(Contract):
        executor:str=Field(min_length=16,max_length=100,repr=False)
        call_key:str=Field(min_length=8,max_length=160)
    @router.post('/ai-relay/jobs/{job_id}/recover')
    def recover(job_id:str,payload:ResumeInput):return relay.resume(job_id,payload.executor,payload.call_key)
