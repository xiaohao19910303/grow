"""选股v2交接：仅冻结、校验和归档；实际筛选和模型请求留在浏览器。"""
import json
import uuid
from datetime import date,datetime,timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import db
from pydantic import Field,StrictBool,model_validator
from copilot.core import digest,encoded,fail,now
from ai_evidence import freeze,inputs,read
from history_sources import record_source
from .contracts import Contract,Identifier
from .browser_execution import BrowserExecution,storage_operation,BrowserOwner
from .rule_screening import ALGORITHM,FIELDS,RuleScreen,RuleDraft,PARSER
from .rules import calendar


class RunInputV2(Contract):
    protocol_version: Literal[2]
    account_id: Identifier
    instrument_ids: list[Identifier] = Field(min_length=1,max_length=20)
    screen: RuleScreen
    executor: str = Field(min_length=16,max_length=100,repr=False)
    template_id: Identifier | None = None
    template_version: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.instrument_ids))!=len(self.instrument_ids):raise ValueError('股票池重复。')
        if (self.template_id is None)!=(self.template_version is None):raise ValueError('模板须包含版本。')
        return self


class Evaluation(Contract):
    instrument_id: Identifier
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    data_date: date | None
    values: dict = Field(max_length=30)
    condition_results: list[StrictBool | None] = Field(max_length=10)
    details: list[dict] = Field(max_length=10)
    status: Literal['matched','excluded','unknown']


class ResultV2(BrowserOwner):
    algorithm: Literal['browser-screen-rational-v2']
    input_hash: str = Field(min_length=64,max_length=64)
    items: list[Evaluation] = Field(max_length=20)
    evaluations: list[Evaluation] = Field(max_length=20)
    total: int = Field(ge=0,le=20)
    unresolved: int = Field(ge=0,le=20)


class AnalysisSelection(BrowserOwner):
    instrument_ids: list[Identifier] = Field(min_length=1,max_length=5)
    model: str = Field(min_length=1,max_length=100)
    question: str = Field(min_length=1,max_length=2000)


class ExecutionV2(BrowserExecution):
    def summary(self,c,run):
        if run.get('protocol_version')!=2:return super().summary(c,run)
        result=self.public(run)
        jobs={iid:self.job_in(c,jid) for iid,jid in run['jobs'].items()}
        result['job_states']={iid:j['state'] for iid,j in jobs.items()}
        result['screen_state']='ready' if run.get('screening') else 'pending'
        result['analysis_state']='not_started'
        if run.get('analysis_selection'):
            states=[j['state'] for j in jobs.values()]
            result['analysis_state']='ready' if len(states)==len(run['analysis_selection']) and all(s=='ready' for s in states) else 'partial' if any(j.get('local_status') or j['state'] in ('failed','cancelled','interrupted') for j in jobs.values()) else 'running'
            if run['state']!='cancelled':result['state']=result['analysis_state']
        return result

    @storage_operation
    def create(self,request,key):
        if not isinstance(request,RunInputV2):return super().create(request,key)
        payload=request.model_dump(mode='json');fingerprint=digest(encoded({'screen_v2':payload}))
        with db.connect() as c:
            self.store.lock(c);self.initialize(c)
            old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            self.store._get(c,'accounts',request.account_id)
            template=None
            if request.template_id:
                template=self.store._get(c,'screening-templates',request.template_id)
                if template['account_id']!=request.account_id or template['version']!=request.template_version or not template['enabled']:
                    fail('template_changed','模板已变化、停用或不属于当前账户。')
            stamp=now();local=datetime.fromisoformat(stamp).astimezone(ZoneInfo('Asia/Shanghai'))
            if request.screen.as_of>local.date():fail('future_date','不能筛选未来日期。',422)
            end=request.screen.as_of;start=end-timedelta(days=100)
            calendars={m:calendar(m,start.isoformat(),end.isoformat(),stamp) for m in ('SSE','SZSE')}
            ref=calendars['SSE'];days=sorted(d for d,opened in ref['sessions'].items() if opened and not (d==local.date().isoformat() and local.hour*60+local.minute<15*60+30))
            target=days[-1] if days else end.isoformat()
            sources=[];universe=[]
            for iid in request.instrument_ids:
                instrument=self.store._get(c,'instruments',iid)
                if instrument['kind']!='stock' or instrument['market'] not in calendars:fail('invalid_scope','首期仅接收指定沪深股票。',422)
                row=c.execute("SELECT data FROM investment_objects WHERE kind='market-snapshots' AND data::jsonb->>'instrument_id'=? ORDER BY created_at DESC,id DESC LIMIT 1",(iid,)).fetchone()
                market=json.loads(row[0]) if row else {}
                if len(market.get('bars',[]))>200:fail('local_scope','单个标的最多200条日线。',422)
                for record in (instrument,market):
                    if record:sources.append(record_source(c,'investment_objects',(record['id'],),instrument['name'],record,fields=['data'],target={'kind':'investment','id':record['id'],'resource':'instruments' if record==instrument else 'market-snapshots','account_id':request.account_id}))
                universe.append({**{k:instrument[k] for k in ('id','name','code','market','kind')},'instrument_id':iid,
                    'bars':market.get('bars',[]),'snapshot_id':market.get('id'),'provider':market.get('provider'),
                    'price_basis':market.get('price_basis'),'retrieved_at':market.get('retrieved_at'),'calendar':calendars[instrument['market']]})
            if template:sources.append(record_source(c,'investment_objects',(template['id'],),template['name'],template,fields=['data']))
            screen=request.screen.model_dump(mode='json');screen['as_of']=target
            bundle={'algorithm':ALGORITHM,'catalog':FIELDS,'requested_as_of':end.isoformat(),'request':screen,'universe':universe,'template_snapshot':template}
            rid='local-run-'+uuid.uuid4().hex
            evidence=freeze(c,'investments',rid,[{'role':'user','content':encoded(bundle)}],'deterministic-screen-v2',sources=[*inputs(bundle),*sources],prompt_version=ALGORITHM,stage='screening')
            run={'id':rid,'state':'awaiting_browser','created_at':stamp,'account_id':request.account_id,'protocol_version':2,'algorithm':ALGORITHM,
                'input_snapshot_id':evidence['id'],'input_hash':evidence['input_hash'],'owner_hash':digest(request.executor),
                'model':None,'question':None,'analysis_selection':[],'jobs':{},'research':{},'research_sources':{},'execution_location':'browser','full_market':False}
            c.execute('INSERT INTO investment_local_runs VALUES (?,?)',(rid,encoded(run)))
            result=self.public(run);self.store.remember(c,key,fingerprint,result);return result

    @storage_operation
    def screen_result(self,rid,request,key):
        if not isinstance(request,ResultV2):return super().screen_result(rid,request,key)
        fingerprint=digest(encoded({'screen_result_v2':rid,'data':request.model_dump(mode='json')}))
        with db.connect() as c:
            self.store.lock(c);old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            run=self.get_in(c,rid);self.owner(run,request.executor)
            if run.get('protocol_version')!=2 or run['state']!='awaiting_browser' or run['input_hash']!=request.input_hash:fail('local_state','批次状态、协议或输入已变化。')
            bundle=json.loads(read(c,run['input_snapshot_id'])['messages'][0]['content']);universe={i['instrument_id']:i for i in bundle['universe']}
            records=[e.model_dump(mode='json') for e in request.evaluations]
            if len(records)!=len(universe) or {e['instrument_id'] for e in records}!=set(universe):fail('invalid_result','评价须逐只覆盖冻结股票池且不重复。',422)
            matched={e['instrument_id']:e for e in records if e['status']=='matched'}
            if len(matched)!=request.total or sum(e['status']=='unknown' for e in records)!=request.unresolved:fail('invalid_result','评价统计不一致。',422)
            if len(request.items)!=min(request.total,bundle['request']['limit']) or len({e.instrument_id for e in request.items})!=len(request.items):fail('invalid_result','候选数量不一致。',422)
            for item in request.items:
                if item.model_dump(mode='json')!=matched.get(item.instrument_id):fail('invalid_result','候选不属于入选评价。',422)
            for e in records:
                original=universe[e['instrument_id']];conditions=bundle['request']['conditions'];outcomes=e['condition_results']
                if e['name']!=original['name'] or e['code']!=original['code'] or set(e['values'])!=set(FIELDS) or len(outcomes)!=len(conditions) or len(e['details'])!=len(conditions):fail('invalid_result','评价身份或字段不匹配。',422)
                for field,value in e['values'].items():
                    if field=='price_above_ma20':
                        if value is not None and type(value)!=bool:fail('invalid_result','均线格式无效。',422)
                    elif value is not None:
                        try:
                            if not isinstance(value,str) or len(value)>100 or not Decimal(value).is_finite():raise ValueError()
                        except (ValueError,ArithmeticError):fail('invalid_result','指标格式无效。',422)
                for condition,outcome,detail in zip(conditions,outcomes,e['details']):
                    if set(detail)!={'field','actual','result','reason','unit'} or detail['field']!=condition['field'] or detail['result'] is not outcome or detail['actual']!=e['values'][condition['field']] or detail['unit']!=FIELDS[condition['field']]['unit'] or (detail['reason'] is not None and (not isinstance(detail['reason'],str) or len(detail['reason'])>200)):
                        fail('invalid_result','逐条件解释不一致。',422)
                expected=('excluded' if False in outcomes else 'unknown' if None in outcomes else 'matched') if bundle['request']['combine']=='all' else ('matched' if True in outcomes else 'unknown' if None in outcomes else 'excluded')
                if not outcomes:expected='matched' if e['values']['close'] is not None else 'unknown'
                if expected!=e['status']:fail('invalid_result','三值评价状态不一致。',422)
                target=bundle['request']['as_of'];bar=next((b for b in original['bars'] if b['date']==target),None)
                if e['data_date']!=(target if bar else None):fail('invalid_result','数据日期不匹配。',422)
                if e['values']['close'] is not None and (not bar or Decimal(e['values']['close'])!=Decimal(bar['close'])):fail('invalid_result','收盘价不属于冻结数据。',422)
            for item in request.items:
                e=item.model_dump(mode='json');original=universe[item.instrument_id]
                bars=[b for b in original['bars'] if b['date']<=bundle['request']['as_of']]
                content=encoded({'algorithm':ALGORITHM,'execution_location':'browser','calculation_verification':'client_reported',
                    'instrument':{k:original[k] for k in ('name','code','kind','market')},'screen_values':e['values'],'rule_request':bundle['request'],
                    'details':e['details'],'bars':bars[-20:],'stored_bar_count':len(bars),'summary_omitted_bar_count':max(0,len(bars)-20),
                    'limitations':['本地自报计算，远端未重算；未复权价格变化不是投资总回报；非全市场或历史回测。']})
                record=self.store.create_in(c,'research',self.store.validate('research',{'account_id':run['account_id'],'instrument_id':item.instrument_id,
                    'title':original['name']+' · 规则选股摘要','content':content,'available_at':now(),'locator':'批次 '+rid}), 'v2-research-'+digest(rid+item.instrument_id))
                run['research'][item.instrument_id]=record
                run['research_sources'][item.instrument_id]=record_source(c,'investment_objects',(record['id'],),record['title'],record,fields=['data'])
            run['screening']=request.model_dump(mode='json',exclude={'executor'});run['state']='screened';self.put(c,run)
            result=self.summary(c,run);self.store.remember(c,key,fingerprint,result);return result

    @storage_operation
    def select_analysis(self,rid,request,key):
        fingerprint=digest(encoded({'selection':rid,'data':request.model_dump(mode='json')}))
        with db.connect() as c:
            self.store.lock(c);old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            run=self.get_in(c,rid);self.owner(run,request.executor)
            if run.get('protocol_version')!=2 or not run.get('screening') or run['state']=='cancelled':fail('local_state','批次尚不能选择候选。')
            if run['analysis_selection']:fail('selection_frozen','候选选择已冻结；更改请新建批次。')
            if len(set(request.instrument_ids))!=len(request.instrument_ids) or any(i not in run['research'] for i in request.instrument_ids):fail('invalid_selection','只能选择本批已入选候选。',422)
            if any(ord(ch)<32 for ch in request.model):fail('invalid_model','模型名无效。',422)
            run.update(analysis_selection=request.instrument_ids,model=request.model,question=request.question)
            self.put(c,run);result=self.summary(c,run);self.store.remember(c,key,fingerprint,result);return result
