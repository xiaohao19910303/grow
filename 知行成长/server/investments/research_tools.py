"""Private immutable research datasets, explained screens and fresh-price alerts."""
import csv
import io
import json
import uuid
from fractions import Fraction
from datetime import date,datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import db
from fastapi import Header,Query
from pydantic import AwareDatetime,Field,StrictBool,model_validator
from copilot.core import digest,encoded,fail,now
from .contracts import Contract,Identifier
from .market_data import canonical_code,MarketDataError
from .rule_screening import finite
from .rules import calendar

TABLES='''CREATE TABLE IF NOT EXISTS investment_research_objects (
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,account_id TEXT NOT NULL REFERENCES investment_accounts(id),
 version INTEGER NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS investment_research_scope ON investment_research_objects(account_id,kind,id);
CREATE TABLE IF NOT EXISTS investment_research_versions (
 object_id TEXT NOT NULL REFERENCES investment_research_objects(id),version INTEGER NOT NULL,data TEXT NOT NULL,
 PRIMARY KEY(object_id,version));'''
FIELDS={'close':'价格（元）','change_1d_pct':'当日变化（%）','volume_shares':'成交量（股）','turnover_cny':'成交额（元）',
 'volume_ratio_5':'来源量比','turnover_rate_pct':'换手率（%）','pe':'动态市盈率','pb':'市净率','roe_pct':'净资产收益率（%）',
 'market_cap_cny':'总市值（元）','revenue_growth_pct':'营收增长（%）','distance_high_pct':'距区间高点（%）','distance_low_pct':'距区间低点（%）'}
for n in (1,3,5,7,10,20,30,60):FIELDS[f'return_{n}d_pct']=f'近{n}日变化（%）'
for n in (5,10,20,60):FIELDS[f'close_to_ma{n}_pct']=f'价格相对MA{n}（%）'


def code(value):
    try:return canonical_code(value)
    except MarketDataError:fail('invalid_code','请核对保留前导零的证券代码和市场。',422)


class Condition(Contract):
    field:str
    op:Literal['gt','gte','lt','lte','eq','ne','between']
    value:str=Field(max_length=100)
    upper_value:str|None=Field(default=None,max_length=100)
    @model_validator(mode='after')
    def valid(self):
        if self.field not in FIELDS:raise ValueError('不支持的字段。')
        low=finite(self.value)
        if self.op=='between':
            if self.upper_value is None or finite(self.upper_value)<low:raise ValueError('区间无效。')
        elif self.upper_value is not None:raise ValueError('单阈值条件不能有上界。')
        return self


class Row(Contract):
    code:str=Field(max_length=20)
    name:str=Field(min_length=1,max_length=100)
    values:dict[str,str|None]=Field(max_length=40)
    known_at:AwareDatetime|None=None
    @model_validator(mode='after')
    def valid(self):
        canonical_code(self.code)
        if not set(self.values)<=set(FIELDS):raise ValueError('未知指标字段。')
        for field,value in self.values.items():
            if value is not None:
                n=finite(value)
                if field in ('close','volume_shares','turnover_cny','turnover_rate_pct','market_cap_cny') and n<0:raise ValueError('数量价格不能为负。')
                if field=='close' and n==0:raise ValueError('价格缺失应填写null。')
        if any(self.values.get(field) is not None for field in ('roe_pct','revenue_growth_pct')) and self.known_at is None:
            raise ValueError('财务指标须包含可知时间。')
        return self


class DatasetInput(Contract):
    account_id:Identifier
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool
    market_date:date
    coverage:Literal['declared_universe','full_market_claimed','specified_pool']='declared_universe'
    expected_count:int|None=Field(default=None,ge=1,le=10000)
    rows:list[Row]=Field(min_length=1,max_length=8000)
    @model_validator(mode='after')
    def valid(self):
        if not self.use_confirmed:raise ValueError('需确认来源用途。')
        identities=[canonical_code(r.code) for r in self.rows]
        if len(set(identities))!=len(identities):raise ValueError('证券重复。')
        if self.expected_count is not None and self.expected_count<len(identities):raise ValueError('实际数大于声明范围。')
        return self


class ScreenInput(Contract):
    account_id:Identifier
    dataset_id:Identifier
    conditions:list[Condition]=Field(default_factory=list,max_length=10)
    combine:Literal['all','any']='all'
    sort_by:str='turnover_cny'
    descending:StrictBool=True
    @model_validator(mode='after')
    def valid(self):
        if self.sort_by not in FIELDS:raise ValueError('排序字段未知。')
        return self


class PresetInput(Contract):
    account_id:Identifier
    name:str=Field(min_length=1,max_length=100)
    conditions:list[Condition]=Field(default_factory=list,max_length=10)
    combine:Literal['all','any']='all'
    sort_by:str='turnover_cny'
    descending:StrictBool=True
    @model_validator(mode='after')
    def valid(self):
        if self.sort_by not in FIELDS:raise ValueError('排序字段无效。')
        return self


class EditInput(Contract):
    version:int=Field(ge=1)
    name:str|None=Field(default=None,min_length=1,max_length=100)
    enabled:StrictBool|None=None
    threshold:str|None=Field(default=None,max_length=100)
    conditions:list[Condition]|None=Field(default=None,max_length=10)
    combine:Literal['all','any']|None=None
    sort_by:str|None=None
    descending:StrictBool|None=None
    archived:StrictBool|None=None


class AlertInput(Contract):
    account_id:Identifier
    code:str=Field(max_length=20)
    name:str=Field(min_length=1,max_length=100)
    field:Literal['price_above','price_below','change_above','change_below']
    threshold:str=Field(max_length=100)
    cooldown_seconds:int=Field(default=86400,ge=60,le=604800)
    max_age_seconds:int=Field(default=300,ge=10,le=900)
    @model_validator(mode='after')
    def valid(self):
        canonical_code(self.code);n=finite(self.threshold)
        if self.field.startswith('price_') and n<=0:raise ValueError('价格阈值须为正。')
        return self


class Quote(Contract):
    code:str=Field(max_length=20)
    price:str=Field(max_length=100)
    previous_close:str|None=Field(default=None,max_length=100)
    quoted_at:AwareDatetime
    @model_validator(mode='after')
    def valid(self):
        canonical_code(self.code)
        if finite(self.price)<=0 or (self.previous_close is not None and finite(self.previous_close)<=0):raise ValueError('报价须为正数。')
        return self


class QuoteCheck(Contract):
    account_id:Identifier
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool
    quotes:list[Quote]=Field(max_length=50)
    @model_validator(mode='after')
    def valid(self):
        ids=[canonical_code(q.code) for q in self.quotes]
        if not self.use_confirmed or len(set(ids))!=len(ids):raise ValueError('需确认来源，报价不能重复。')
        return self


class CandidateInput(Contract):
    account_id:Identifier
    dataset_id:Identifier
    code:str=Field(max_length=20)


def evaluate(row,conditions,combine):
    details=[]
    for c in conditions:
        raw=row['values'].get(c['field']);result=None
        if raw is not None:
            actual=finite(raw);target=finite(c['value'])
            if c['op']=='between':result=target<=actual<=finite(c['upper_value'])
            else:result={'gt':actual>target,'gte':actual>=target,'lt':actual<target,'lte':actual<=target,'eq':actual==target,'ne':actual!=target}[c['op']]
        details.append({'field':c['field'],'actual':raw,'result':result,'reason':'source_field_missing' if raw is None else 'source_provided'})
    results=[d['result'] for d in details]
    status=('excluded' if False in results else 'unknown' if None in results else 'matched') if combine=='all' else ('matched' if True in results else 'unknown' if None in results else 'excluded')
    if not conditions:status='matched'
    return {**row,'status':status,'details':details}


class ResearchTools:
    def __init__(self,store):self.store=store
    def initialize(self,c):
        # First-page lists arrive concurrently; PostgreSQL IF NOT EXISTS alone
        # cannot serialize concurrent creation of the same catalog objects.
        self.store.lock(c);c.executescript(TABLES)
    def get(self,c,identity,kind=None,account_id=None):
        row=c.execute('SELECT kind,account_id,data FROM investment_research_objects WHERE id=?',(identity,)).fetchone()
        if not row or (kind and row[0]!=kind):fail('not_found','研究记录不存在。',404)
        if account_id and row[1]!=account_id:fail('research_scope','研究资料不属于当前投资账户。',422)
        return json.loads(row[2])
    def save(self,c,kind,account_id,data,record=None):
        stamp=now();self.store._get(c,'accounts',account_id)
        result={'id':record['id'] if record else 'research-'+uuid.uuid4().hex,'kind':kind,'account_id':account_id,
            'version':record['version']+1 if record else 1,'created_at':record['created_at'] if record else stamp,
            'updated_at':stamp,'input_hash':digest(encoded(data)),'data':data}
        c.execute('INSERT INTO investment_research_objects VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,data=excluded.data',
            (result['id'],kind,account_id,result['version'],encoded(result)))
        c.execute('INSERT INTO investment_research_versions VALUES (?,?,?)',(result['id'],result['version'],encoded(result)))
        return result
    def create(self,kind,account_id,data,key,fingerprint=None):
        fingerprint=fingerprint or digest(encoded({'research':kind,'account_id':account_id,'data':data}))
        with db.connect() as c:
            self.store.lock(c);self.initialize(c);old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            result=self.save(c,kind,account_id,data);self.store.remember(c,key,fingerprint,result);return result
    def dataset(self,payload,key):
        data=payload.model_dump(mode='json',exclude={'account_id','use_confirmed'})
        local=datetime.fromisoformat(now()).astimezone(ZoneInfo('Asia/Shanghai'))
        if payload.market_date>local.date() or any(r.known_at and r.known_at>local for r in payload.rows):fail('future_data','不能导入未来数据或未来可知资料。',422)
        for row in data['rows']:row['code']=code(row['code'])
        data.update(captured_at=now(),source_verification='user_declared',metrics_origin='source_provided',actual_count=len(data['rows']))
        fingerprint=digest(encoded({'dataset':payload.model_dump(mode='json')}))
        return self.create('dataset',payload.account_id,data,key,fingerprint)
    def screen(self,payload,key):
        with db.connect() as c:
            self.initialize(c);dataset=self.get(c,payload.dataset_id,'dataset',payload.account_id)
        request=payload.model_dump(mode='json');data=dataset['data']
        rows=[evaluate(r,request['conditions'],request['combine']) for r in data['rows']]
        matching=[r for r in rows if r['status']=='matched']
        matching.sort(key=lambda r:r['code'])
        available=[r for r in matching if r['values'].get(payload.sort_by) is not None]
        available.sort(key=lambda r:finite(r['values'][payload.sort_by]),reverse=payload.descending)
        items=available+[r for r in matching if r['values'].get(payload.sort_by) is None]
        result={'request':request,'dataset_hash':dataset['input_hash'],'market_date':data['market_date'],
            'coverage':data['coverage'],'actual_count':len(rows),'expected_count':data['expected_count'],
            'matched':len(items),'unknown':sum(r['status']=='unknown' for r in rows),
            'items':items,'evaluations':rows,'algorithm':'declared-market-screen-v1','metrics_origin':'source_provided'}
        return self.create('screen',payload.account_id,result,key)
    def edit(self,identity,payload,key):
        fingerprint=digest(encoded({'edit_research':identity,'data':payload.model_dump(mode='json')}))
        with db.connect() as c:
            self.store.lock(c);self.initialize(c);old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            record=self.get(c,identity)
            if record['kind'] not in ('preset','alert'):fail('immutable','历史数据与结果不能覆盖，请新建版本。',409)
            if record['kind']=='preset' and payload.threshold is not None:fail('validation_error','筛选方案不接收提醒阈值。',422)
            if record['kind']=='alert' and any(getattr(payload,f) is not None for f in ('conditions','combine','sort_by','descending')):fail('validation_error','提醒不接收筛选方案字段。',422)
            if record['version']!=payload.version:fail('version_conflict','记录已变化，请重新读取后修改。',409)
            data=record['data'].copy();data.update(payload.model_dump(exclude_none=True,exclude={'version'}))
            if payload.archived:data['enabled']=False
            if record['kind']=='preset':PresetInput.model_validate({k:v for k,v in {**data,'account_id':record['account_id']}.items() if k in PresetInput.model_fields})
            if record['kind']=='alert':
                AlertInput.model_validate({k:v for k,v in {**data,'account_id':record['account_id']}.items() if k in AlertInput.model_fields})
            result=self.save(c,record['kind'],record['account_id'],data,record);self.store.remember(c,key,fingerprint,result);return result
    def listing(self,account_id,kind,page=1,page_size=50):
        with db.connect() as c:
            self.initialize(c);self.store._get(c,'accounts',account_id)
            where="account_id=? AND kind=? AND COALESCE((data::jsonb->'data'->>'archived')::boolean,false)=false";args=(account_id,kind)
            total=c.execute('SELECT count(*) FROM investment_research_objects WHERE '+where,args).fetchone()[0]
            rows=[json.loads(r[0]) for r in c.execute("SELECT data FROM investment_research_objects WHERE "+where+" ORDER BY data::jsonb->>'created_at' DESC,id DESC LIMIT ? OFFSET ?",(*args,page_size,(page-1)*page_size))]
        for row in rows:
            row['data']={k:v for k,v in row['data'].items() if k not in ('rows','bars','items','evaluations','equity','trades','out_of_sample','sensitivity')}
            if row['kind']=='backtest':row['data']['result']={k:v for k,v in row['data']['result'].items() if k not in ('equity','trades','orders')}
        return {'items':rows,'total':total,'page':page,'page_size':page_size}
    def export(self,account_id):
        with db.connect() as c:
            self.initialize(c);self.store._get(c,'accounts',account_id)
            size=c.execute('SELECT COALESCE(sum(octet_length(data)),0) FROM investment_research_objects WHERE account_id=?',(account_id,)).fetchone()[0]
            size+=c.execute('SELECT COALESCE(sum(octet_length(v.data)),0) FROM investment_research_versions v JOIN investment_research_objects o ON o.id=v.object_id WHERE o.account_id=?',(account_id,)).fetchone()[0]
            if size>20_000_000:fail('export_size','研究资料较多，请使用管理员完整备份。',422)
            rows=[json.loads(r[0]) for r in c.execute('SELECT data FROM investment_research_objects WHERE account_id=? ORDER BY id',(account_id,))]
            versions=[json.loads(r[0]) for r in c.execute('SELECT v.data FROM investment_research_versions v JOIN investment_research_objects o ON o.id=v.object_id WHERE o.account_id=? ORDER BY v.object_id,v.version',(account_id,))]
        return {'format':'grow-investment-research-v1','scope':'当前投资账户的研究数据、方案、提醒、回测及历史版本；不含登录、模型或接口凭证。','exported_at':now(),'objects':rows,'versions':versions}
    def check(self,payload,key):
        fingerprint=digest(encoded({'quotes':payload.model_dump(mode='json')}));stamp=now();instant=datetime.fromisoformat(stamp).astimezone(ZoneInfo('Asia/Shanghai'))
        by_code={code(q.code):q for q in payload.quotes};events=[];checks=[]
        with db.connect() as c:
            self.store.lock(c);self.initialize(c);self.store._get(c,'accounts',payload.account_id);old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            alerts=[json.loads(r[0]) for r in c.execute("SELECT data FROM investment_research_objects WHERE account_id=? AND kind='alert'",(payload.account_id,))]
            for alert in alerts:
                data=alert['data'];symbol=code(data['code']);quote=by_code.get(symbol);reason=None;triggered=False
                if data.get('archived'):reason='archived'
                elif not data.get('enabled',True):reason='disabled'
                elif quote is None:reason='missing'
                else:
                    age=(instant-quote.quoted_at).total_seconds()
                    market={'SH':'SSE','SZ':'SZSE','BJ':'BSE'}[symbol[-2:]];cal=calendar(market,instant.date().isoformat(),instant.date().isoformat(),stamp)
                    minutes=instant.hour*60+instant.minute
                    if cal['status']!='available':reason='calendar_unknown'
                    elif not cal['sessions'].get(instant.date().isoformat()) or not (570<=minutes<690 or 780<=minutes<900):reason='closed'
                    elif age<0 or age>data['max_age_seconds'] or quote.quoted_at.astimezone(ZoneInfo('Asia/Shanghai')).date()!=instant.date():reason='stale'
                    elif data.get('last_triggered_at') and (instant-datetime.fromisoformat(data['last_triggered_at'])).total_seconds()<data['cooldown_seconds']:reason='cooldown'
                    else:
                        value=Fraction(finite(quote.price))
                        if data['field'].startswith('change_'):
                            if quote.previous_close is None:reason='previous_close_missing'
                            else:value=(value/Fraction(finite(quote.previous_close))-1)*100
                        if reason is None:
                            threshold=Fraction(finite(data['threshold']));triggered=value>threshold if data['field'].endswith('above') else value<threshold
                            reason='triggered' if triggered else 'not_met'
                if triggered:
                    event=self.save(c,'alert-event',payload.account_id,{'alert_id':alert['id'],'code':symbol,'name':data['name'],
                        'field':data['field'],'threshold':data['threshold'],'quote':quote.model_dump(mode='json'),
                        'triggered_at':stamp,'source_label':payload.source_label,'quote_hash':digest(encoded(quote.model_dump(mode='json')))})
                    events.append(event);self.save(c,'alert',payload.account_id,{**data,'last_triggered_at':stamp},alert)
                checks.append({'alert_id':alert['id'],'code':symbol,'status':reason})
            result={'events':events,'checks':checks,'checked_at':stamp,'notification_delivery':'browser_when_open'}
            self.store.remember(c,key,fingerprint,result);return result


def register(router,store):
    service=ResearchTools(store)
    @router.get('/research/catalog')
    def catalog():return {'fields':FIELDS,'max_rows':8000,'max_conditions':10,'metrics_origin':'source_provided'}
    @router.get('/research/export')
    def export(account_id:str):return service.export(account_id)
    @router.post('/research/datasets',status_code=201)
    def dataset(payload:DatasetInput,idempotency_key:str=Header(min_length=8,max_length=160)):return service.dataset(payload,idempotency_key)
    @router.post('/research/screens',status_code=201)
    def screen(payload:ScreenInput,idempotency_key:str=Header(min_length=8,max_length=160)):return service.screen(payload,idempotency_key)
    @router.post('/research/candidate',status_code=201)
    def candidate(payload:CandidateInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        fingerprint=digest(encoded({'research_candidate':payload.model_dump(mode='json')}))
        with db.connect() as c:
            store.lock(c);service.initialize(c);old=store.replay(c,idempotency_key,fingerprint)
            if old is not None:return old
            dataset=service.get(c,payload.dataset_id,'dataset',payload.account_id);symbol=code(payload.code)
            selected=next((row for row in dataset['data']['rows'] if row['code']==symbol),None)
            if selected is None:fail('not_found','候选不属于该冻结数据集。',404)
            instrument=store.create_in(c,'instruments',store.validate('instruments',{'name':selected['name'],'code':symbol[:6],
                'market':{'SH':'SSE','SZ':'SZSE','BJ':'BSE'}[symbol[-2:]],'kind':'etf' if symbol[0] in '15' else 'stock'}),'candidate-instrument-'+digest(idempotency_key))
            evidence=store.create_in(c,'research',store.validate('research',{'account_id':payload.account_id,'instrument_id':instrument['id'],
                'title':selected['name']+' · 全市场条件研究','content':encoded({'dataset_id':dataset['id'],'dataset_hash':dataset['input_hash'],'market_date':dataset['data']['market_date'],
                    'source_label':dataset['data']['source_label'],'selected':selected,'limitations':['来源指标尚未独立核验；上市身份、时效与可交易性仍需核对。']}),
                'available_at':now(),'locator':'冻结市场数据集 '+dataset['id']}),'candidate-evidence-'+digest(idempotency_key))
            result={'instrument':instrument,'evidence':evidence};store.remember(c,idempotency_key,fingerprint,result);return result
    @router.post('/research/presets',status_code=201)
    def preset(payload:PresetInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        return service.create('preset',payload.account_id,{**payload.model_dump(mode='json',exclude={'account_id'}),'enabled':True},idempotency_key)
    @router.post('/research/alerts',status_code=201)
    def alert(payload:AlertInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        return service.create('alert',payload.account_id,{**payload.model_dump(mode='json',exclude={'account_id'}),'code':code(payload.code),'enabled':True,'last_triggered_at':None},idempotency_key)
    @router.post('/research/alerts/check')
    def check(payload:QuoteCheck,idempotency_key:str=Header(min_length=8,max_length=160)):return service.check(payload,idempotency_key)
    def edit(kind,identity,payload,idempotency_key):
        with db.connect() as c:service.initialize(c);service.get(c,identity,kind)
        return service.edit(identity,payload,idempotency_key)
    @router.post('/research/alerts/{identity}')
    def edit_alert(identity:str,payload:EditInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        return edit('alert',identity,payload,idempotency_key)
    @router.post('/research/presets/{identity}')
    def edit_preset(identity:str,payload:EditInput,idempotency_key:str=Header(min_length=8,max_length=160)):
        return edit('preset',identity,payload,idempotency_key)
    @router.get('/research/objects/{identity}')
    def detail(identity:str):
        with db.connect() as c:service.initialize(c);return service.get(c,identity)
    @router.get('/research/objects')
    def listing(account_id:str,kind:str=Query(pattern='^(dataset|screen|preset|alert|alert-event|series|backtest)$'),page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):
        return service.listing(account_id,kind,page,page_size)
    return service
