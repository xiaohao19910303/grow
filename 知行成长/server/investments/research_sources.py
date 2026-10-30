"""Explicit CSV, configured HTTPS interfaces and bounded AKShare research adapters."""
import asyncio
import csv
import io
import json
import os
import subprocess
import sys
import threading
from datetime import date,datetime,timedelta
from decimal import Decimal,localcontext
from pathlib import Path
from typing import Literal

import db
import httpx
from fastapi import Header
from pydantic import Field,StrictBool
from zoneinfo import ZoneInfo
from copilot.core import digest,encoded,fail,now,Problem
from .contracts import Contract,Identifier
from .bounded_http import public_addresses,PinnedTransport
from .market_data import canonical_code
from .research_tools import DatasetInput,FIELDS,QuoteCheck
from .research_history import SeriesInput,HistoricalBar,save_series,timestamp
from .rules import calendar

_slot=threading.BoundedSemaphore(1)


def worker(request):
    if not _slot.acquire(blocking=False):fail('provider_busy','已有行情读取进行中，请稍后手动重试。',409)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','TMPDIR','PYTHONPATH','SSL_CERT_FILE','SSL_CERT_DIR')}
    try:
        response=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('research_worker.py'))],input=encoded(request),capture_output=True,text=True,timeout=90,env=env)
        if response.returncode or len(response.stdout)>8_000_000:raise ValueError()
        packet=json.loads(response.stdout)
        if packet.get('error'):
            errors={'dependency_missing':('provider_dependency_missing','服务端缺少锁定的AKShare依赖。',503),
                'upstream_connection':('provider_connection','所选上游连接中断，可能受到网络或上游访问限制；可稍后明确新建读取，或手动选择其他上游。未自动重试或换源。',502),
                'upstream_rate_limit':('provider_rate_limited','所选上游返回限流，请稍后再试；未自动重试或换源。',429),
                'upstream_timeout':('provider_timeout','所选上游响应超时，旧资料保留；未自动重试或换源。',504),
                'upstream_format':('provider_invalid','所选上游返回字段不完整或格式变化，未保存本次资料。',502)}
            code,message,status=errors.get(packet['error'],('provider_unavailable','所选行情上游未返回有效结果，旧资料保留；请稍后手动重试或选择其他上游。',502));fail(code,message,status)
        if not isinstance(packet.get('rows'),list):raise ValueError()
        return packet
    except subprocess.TimeoutExpired:fail('provider_timeout','行情读取超过90秒已停止，未自动重试或换源。',504)
    except (OSError,ValueError,TypeError):fail('provider_unavailable','行情返回格式无法读取，原数据保留。',502)
    finally:_slot.release()


class DatasetCSV(Contract):
    account_id:Identifier
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool
    market_date:date
    coverage:Literal['declared_universe','full_market_claimed','specified_pool']='declared_universe'
    expected_count:int|None=Field(default=None,ge=1,le=10000)
    text:str=Field(min_length=1,max_length=4000000,repr=False)


class AKMarket(Contract):
    account_id:Identifier
    use_confirmed:StrictBool
    source:Literal['eastmoney','tencent']='eastmoney'


class AKHistory(AKMarket):
    code:str=Field(max_length=20)
    name:str=Field(min_length=1,max_length=100)
    kind:Literal['stock','etf']='stock'
    interval:Literal['day','minute']='day'
    start:date
    end:date
    refresh:StrictBool=False


class InterfaceInput(Contract):
    account_id:Identifier
    kind:Literal['dataset','quotes','series']
    url:str=Field(min_length=1,max_length=2048,repr=False)
    token:str=Field(default='',max_length=4096,repr=False)
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool


def numeric(value,multiplier='1',positive=False):
    if value is None or str(value).lower() in ('','nan','none','--','null'):return None
    try:
        with localcontext() as ctx:
            ctx.prec=80;n=Decimal(str(value))*Decimal(multiplier)
            if not n.is_finite() or abs(n)>=Decimal('1e20') or (positive and n<=0):return None
            return format(n,'f')
    except (ValueError,ArithmeticError):return None


def normalize_spot(rows,source='eastmoney'):
    if source=='tencent':
        mapping={'close':'zxj','change_1d_pct':'zdf','volume_shares':'volume','turnover_cny':'turnover','volume_ratio_5':'lb','turnover_rate_pct':'hsl','pe_ttm':'pe_ttm','pb':'pn','market_cap_cny':'zsz','return_5d_pct':'zdf_d5','return_10d_pct':'zdf_d10','return_20d_pct':'zdf_d20','return_60d_pct':'zdf_d60'}
        scales={'volume_shares':'100','turnover_cny':'10000','market_cap_cny':'100000000'}
        return [{'code':canonical_code(r['code']),'name':r['name'],'values':{k:numeric(r.get(v),scales.get(k,'1'),k=='close') for k,v in mapping.items()}} for r in rows]
    mapping={'close':'最新价','change_1d_pct':'涨跌幅','volume_shares':'成交量','turnover_cny':'成交额','volume_ratio_5':'量比',
             'turnover_rate_pct':'换手率','pe':'市盈率-动态','pb':'市净率','market_cap_cny':'总市值','return_60d_pct':'60日涨跌幅'}
    return [{'code':canonical_code(r['代码']),'name':r['名称'],'values':{k:numeric(r.get(v),'100' if k=='volume_shares' else '1',k=='close') for k,v in mapping.items()}} for r in rows]


def parse_market_csv(payload):
    reader=csv.DictReader(io.StringIO(payload.text));rows=[]
    if not reader.fieldnames or not {'code','name'}<=set(reader.fieldnames) or not set(reader.fieldnames)<={'code','name','known_at',*FIELDS}:
        fail('csv_fields','CSV需包含code、name及目录中的指标字段。',422)
    for raw in reader:
        if len(rows)>=8000:fail('csv_size','市场数据最多8000只。',422)
        row={'code':raw.get('code',''),'name':raw.get('name',''),'values':{k:(v.strip() or None) for k,v in raw.items() if k in FIELDS and isinstance(v,str)}}
        if raw.get('known_at'):
            try:row['known_at']=timestamp(raw['known_at'])
            except (ValueError,TypeError):fail('csv_row',f'第{len(rows)+2}行可知时间无效。',422)
        rows.append(row)
    return DatasetInput(**payload.model_dump(exclude={'text'}),rows=rows)


async def interface_json(payload):
    if not payload.use_confirmed:fail('source_consent','请先确认接口来源与用途。',422)
    hosts=[h.strip().lower() for h in os.getenv('INVESTMENT_MARKET_HOSTS','').split(',') if h.strip() and '*' not in h]
    addresses=await asyncio.to_thread(public_addresses,payload.url,hosts)
    transport=PinnedTransport(payload.url,addresses)
    try:
        async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=httpx.Timeout(30,connect=10)) as client:
            async with client.stream('GET',payload.url,headers={'Accept':'application/json',**({'Authorization':'Bearer '+payload.token} if payload.token else {})}) as response:
                if response.status_code!=200:fail('source_response','配置的行情接口未返回成功结果，旧数据保留。',502)
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>8_000_000:fail('source_size','接口响应超过8MB，未保存。',413)
                return json.loads(data)
    except Exception as error:
        if isinstance(error,Problem):raise
        fail('source_unavailable','行情接口连接或格式未通过，旧资料保留；不会自动重试。',502)
    finally:payload.token=''


def register(router,service):
    def reserve_source(account_id,key,fingerprint,save_key):
        with db.connect() as c:
            service.store.lock(c);service.store._get(c,'accounts',account_id)
            fetch_key='research-source-'+digest(key)
            old=service.store.replay(c,fetch_key,fingerprint)
            if old is not None:
                row=c.execute('SELECT response FROM investment_requests WHERE request_key=?',(save_key,)).fetchone()
                if row:return json.loads(row[0])
                fail('source_uncertain','原读取结果未确认，不会自动重新请求；请核对后新建读取。',409)
            service.store.remember(c,fetch_key,fingerprint,{'_source_pending':True})

    @router.post('/research/datasets/csv',status_code=201)
    def market_csv(payload:DatasetCSV,idempotency_key:str=Header(min_length=8,max_length=160)):return service.dataset(parse_market_csv(payload),idempotency_key)

    @router.post('/research/provider/akshare/market',status_code=201)
    def market(payload:AKMarket,idempotency_key:str=Header(min_length=8,max_length=160)):
        if not payload.use_confirmed:fail('source_consent','请确认来源及用途。',422)
        request=payload.model_dump(mode='json')
        if payload.source=='eastmoney':request.pop('source')
        fingerprint=digest(encoded({'ak_market':request}))
        with db.connect() as c:
            service.store._get(c,'accounts',payload.account_id);old=service.store.replay(c,idempotency_key,fingerprint)
            if old is not None:return old
        instant=datetime.fromisoformat(now()).astimezone(ZoneInfo('Asia/Shanghai'));end=instant.date()
        if instant.hour*60+instant.minute<930:end-=timedelta(days=1)
        ref=calendar('SSE',(end-timedelta(days=10)).isoformat(),end.isoformat(),now())
        if ref['status']!='available':fail('calendar_unknown','公开日历当前未覆盖，未读取全市场数据。',422)
        sessions=[d for d,opened in ref['sessions'].items() if opened]
        if not sessions:fail('calendar_unknown','缺少已核对交易日。',422)
        old=reserve_source(payload.account_id,idempotency_key,fingerprint,idempotency_key)
        if old is not None:return old
        packet=worker({'task':'market','source':payload.source})
        if packet.get('upstream',payload.source)!=payload.source:fail('provider_identity','返回上游与本人选择不一致，未保存。',502)
        rows=normalize_spot(packet['rows'],payload.source)
        source_name='腾讯' if payload.source=='tencent' else '东方财富'
        validated=DatasetInput(account_id=payload.account_id,source_label='AKShare / '+source_name+'全市场快照 · '+packet.get('library_version','unknown'),use_confirmed=True,market_date=sessions[-1],coverage='full_market_claimed',rows=rows)
        data=validated.model_dump(mode='json',exclude={'account_id','use_confirmed'})
        data.update(upstream=payload.source,adapter_version=packet.get('adapter_version','akshare-selected-v1'),source_units={'volume':'lots100','amount':'ten_thousand_cny' if payload.source=='tencent' else 'cny','market_cap':'hundred_million_cny' if payload.source=='tencent' else 'cny'},captured_at=now(),actual_count=len(rows),metrics_origin='source_provided',source_verification='not_independently_verified',market_date_verification='reference_date_only_upstream_has_no_quote_timestamp')
        return service.create('dataset',payload.account_id,data,idempotency_key,fingerprint)

    @router.post('/research/provider/akshare/history',status_code=201)
    def history(payload:AKHistory,idempotency_key:str=Header(min_length=8,max_length=160)):
        canonical=canonical_code(payload.code)
        provider_request={**payload.model_dump(mode='json',exclude={'account_id','use_confirmed','refresh'}),'code':canonical}
        if payload.source=='eastmoney':provider_request.pop('source')
        elif payload.kind!='stock' or payload.interval!='day' or canonical.endswith('.BJ') or canonical[:3] not in ('000','001','002','003','300','301','600','601','603','605','688'):fail('provider_scope','腾讯历史目前仅支持沪深股票日线；分钟、ETF及北交所请明确选择东方财富或导入CSV。',422)
        fingerprint=digest(encoded({'ak_history':provider_request,'account_id':payload.account_id,'refresh':payload.refresh}))
        if not payload.use_confirmed or payload.start>payload.end or (payload.end-payload.start).days>(90 if payload.interval=='day' else 7):fail('source_range','请确认来源，并选择日线90天以内或分钟7天以内。',422)
        instant=datetime.fromisoformat(now()).astimezone(ZoneInfo('Asia/Shanghai'))
        if payload.end>instant.date() or (payload.end==instant.date() and instant.hour*60+instant.minute<930):fail('source_range','此入口只读取已完成的盘后资料。',422)
        with db.connect() as c:
            service.store.lock(c);service.initialize(c);service.store._get(c,'accounts',payload.account_id)
            old=service.store.replay(c,idempotency_key,fingerprint)
            if old is not None:return old
            if not payload.refresh:
                for row in c.execute("SELECT data FROM investment_research_objects WHERE account_id=? AND kind='series' ORDER BY data::jsonb->>'created_at' DESC,id DESC LIMIT 100",(payload.account_id,)):
                    saved=json.loads(row[0])
                    if saved['data'].get('provider_request')==provider_request:
                        service.store.remember(c,idempotency_key,fingerprint,saved)
                        return saved
        old=reserve_source(payload.account_id,idempotency_key,fingerprint,idempotency_key)
        if old is not None:return old
        packet=worker({'task':'history','source':payload.source,'code':canonical[:6],'kind':payload.kind,'interval':payload.interval,'start':payload.start.isoformat(),'end':payload.end.isoformat()})
        if packet.get('upstream',payload.source)!=payload.source:fail('provider_identity','返回上游与本人选择不一致，未保存。',502)
        bars=[]
        for raw in packet['rows']:
            stamp=timestamp(raw.get('日期') or raw.get('时间'),payload.interval=='day')
            if not payload.start<=datetime.fromisoformat(stamp).date()<=payload.end:fail('provider_range','来源返回了所选范围外的行情，未保存。',422)
            bars.append({'time':stamp,**{key:numeric(raw.get(source),positive=True) for key,source in [('open','开盘'),('high','最高'),('low','最低'),('close','收盘')]},
                'volume_shares':numeric(raw.get('成交量'),'1' if packet.get('volume_unit')=='shares' else '100'),'turnover_cny':numeric(raw.get('成交额'))})
        source=SeriesInput(account_id=payload.account_id,code=canonical,name=payload.name,interval=payload.interval,price_basis='unadjusted',source_label='AKShare / '+('腾讯' if payload.source=='tencent' else '东方财富')+' · '+packet.get('library_version','unknown'),use_confirmed=True,bars=bars)
        return save_series(service,source,idempotency_key,{'provider_request':provider_request,'upstream':payload.source,'adapter_version':packet.get('adapter_version','akshare-selected-v1')},fingerprint)

    @router.post('/research/interface')
    async def interface(payload:InterfaceInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        fetch_key='research-source-'+digest(idempotency_key);save_key='research-source-save-'+digest(idempotency_key)
        fingerprint=digest(encoded(payload.model_dump(mode='json',exclude={'token'})))
        with db.connect() as c:
            service.store.lock(c);service.store._get(c,'accounts',payload.account_id)
            old=service.store.replay(c,fetch_key,fingerprint)
            if old is not None:
                if old.get('_source_pending'):
                    row=c.execute('SELECT response FROM investment_requests WHERE request_key=?',(save_key,)).fetchone()
                    if row:return json.loads(row[0])
                    fail('source_uncertain','原接口读取结果未确认，不会自动重新请求；请核对后新建读取。',409)
                return old
            service.store.remember(c,fetch_key,fingerprint,{'_source_pending':True})
        try:
            result=await interface_json(payload)
            if not isinstance(result,dict):fail('source_response','接口需返回约定的JSON对象。',422)
            data={**result,'account_id':payload.account_id,'source_label':payload.source_label,'use_confirmed':True}
            if payload.kind=='dataset':saved=await asyncio.to_thread(service.dataset,DatasetInput.model_validate(data),save_key)
            elif payload.kind=='series':saved=await asyncio.to_thread(save_series,service,SeriesInput.model_validate(data),save_key)
            else:saved=await asyncio.to_thread(service.check,QuoteCheck.model_validate(data),save_key)
            with db.connect() as c:
                service.store.lock(c);c.execute('UPDATE investment_requests SET response=? WHERE request_key=?',(encoded(saved),fetch_key))
            return saved
        finally:payload.token=''
