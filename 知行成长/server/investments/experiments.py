"""Prospective observational protocols; no optimization, risk expansion or synthetic fills."""
import json
import uuid
from datetime import datetime,timedelta
from decimal import Decimal,localcontext
import db
from pydantic import AwareDatetime,Field,ValidationError,field_validator,model_validator
from copilot.core import digest,encoded,fail,now
from .contracts import Contract,Identifier,Money
from .accounting import number
from .campaigns import project
from .replay import stamp

class ExperimentInput(Contract):
    account_id: Identifier
    strategy_id: Identifier
    strategy_version: int = Field(ge=1)
    title: str = Field(min_length=1,max_length=200)
    hypothesis: str = Field(min_length=1,max_length=3000)
    counter_case: str = Field(min_length=1,max_length=3000)
    stop_condition: str = Field(min_length=1,max_length=2000)
    parameters: dict[str,str] = Field(min_length=1,max_length=20)
    cost_assumptions: str = Field(min_length=1,max_length=2000)
    start_at: AwareDatetime
    end_at: AwareDatetime
    sample_target: int = Field(ge=1,le=1000)
    additional_roundtrip_costs: list[Money] = Field(min_length=1,max_length=5)

    @field_validator('parameters')
    @classmethod
    def bounded_parameters(cls,value):
        if any(not k.strip() or len(k)>100 or not v.strip() or len(v)>500 for k,v in value.items()):raise ValueError('参数须为有界的文字，不执行代码。')
        return value

    @model_validator(mode='after')
    def window(self):
        if not self.start_at<self.end_at<=self.start_at+timedelta(days=366):raise ValueError('试验期间须按顺序且最多一年。')
        return self


def validated(payload):
    try:return ExperimentInput.model_validate(payload).model_dump(mode='json')
    except ValidationError:fail('invalid_experiment','请补齐假设、反例、参数、成本、起止时间和样本目标，金额用十进制字符串。',422)


def references(store,c,data):
    store._get(c,'accounts',data['account_id']);strategy=store._get(c,'strategies',data['strategy_id'])
    if strategy['version']!=data['strategy_version'] or strategy['state']!='confirmed':
        fail('strategy_version_conflict','请选当前已确认策略版本；更改参数应另建新试验。',422)
    return strategy


def create_experiment(store,payload,key):
    data=validated(payload);fingerprint=digest(encoded({'experiment_create':data}))
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        references(store,c,data);created=now()
        record={**data,'id':'experiment-'+uuid.uuid4().hex,'version':1,'state':'draft','created_at':created,'updated_at':created}
        store.save(c,'experiments',record,fresh=True);store.remember(c,key,fingerprint,record);return record


def update_experiment(store,object_id,version,changes,key):
    fingerprint=digest(encoded({'experiment_update':object_id,'version':version,'changes':changes}))
    with db.connect() as c:
        store.lock(c);replay=store.replay(c,key,fingerprint)
        if replay is not None:return replay
        old=store._get(c,'experiments',object_id)
        if old['version']!=version or old['state']!='draft':fail('immutable_protocol','只有当前草稿版本可修改；登记后的参数和期间不覆盖。',409)
        if not set(changes).issubset(ExperimentInput.model_fields):fail('invalid_experiment','不允许修改生成状态或冻结快照。',422)
        data=validated({**{k:old[k] for k in ExperimentInput.model_fields},**changes})
        if data['account_id']!=old['account_id']:fail('scope_mismatch','试验不能移到其他账户。',422)
        references(store,c,data);record={**old,**data,'version':version+1,'updated_at':now()}
        store.save(c,'experiments',record);store.remember(c,key,fingerprint,record);return record


def register_experiment(store,object_id,version,key):
    fingerprint=digest(encoded({'experiment_register':object_id,'version':version}))
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        record=store._get(c,'experiments',object_id);created=now()
        if record['version']!=version or record['state']!='draft':fail('version_conflict','只有当前草稿可事前登记。')
        strategy=references(store,c,record)
        if stamp(record['start_at'])<stamp(created) or stamp(strategy['updated_at'])>stamp(created):
            fail('retrospective_experiment','试验须在开始前登记，不能把已经发生的结果当作事前试验。',422)
        protocol={k:record[k] for k in ExperimentInput.model_fields};protocol.update(strategy_snapshot=strategy,registered_at=created,
            sample_type='prospectively_registered_observational',selection='全部相符冻结策略版本且在窗口入场的交易链，不按盈亏挑选')
        record={**record,'version':version+1,'state':'registered','registered_at':created,'updated_at':created,
            'protocol_snapshot':protocol,'protocol_hash':digest(encoded(protocol))}
        store.save(c,'experiments',record);store.remember(c,key,fingerprint,record);return record


def evaluate_in(store,c,record):
    if record['state']=='draft':fail('unregistered_experiment','草稿尚未登记，不生成前向评价。',422)
    protocol=record['protocol_snapshot'];start=stamp(protocol['start_at']);end=min(stamp(now()),stamp(protocol['end_at']),stamp(record.get('finished_at') or protocol['end_at']))
    account=store._get(c,'accounts',record['account_id']);observed=[];excluded=[]
    for cycle in store._campaigns(c,record['account_id']):
        if cycle['id'].startswith('opening-'):continue
        entered=stamp(cycle['opened_at'])
        if entered<start or entered>end:continue
        prefix=[f for f in cycle['fills'] if stamp(f['executed_at'])<=end]
        strategies={(f.get('strategy_snapshot',{}).get('id'),f.get('strategy_snapshot',{}).get('version')) for f in prefix if f['side']=='buy'}
        if strategies!={(protocol['strategy_id'],protocol['strategy_version'])}:
            excluded.append({'campaign_id':cycle['id'],'reason':'其他、混合或未冻结策略版本'});continue
        projected=project({**account,'opening_positions':[]},prefix)[0]
        if cycle.get('reconciliation_required'):projected.update(net_realized=None,realized_r=None)
        observed.append({k:projected[k] for k in ('id','state','opened_at','closed_at','quantity','net_realized','fees_complete','risk_basis','realized_r')})
        observed[-1].update(ledger_hash=digest(encoded(prefix)),pre_recorded_plan=all(f.get('plan_valid_at_execution') for f in prefix if f['side']=='buy'))
        if len(observed)+len(excluded)>1000:fail('experiment_too_large','单次试验最多核对1000条交易链，请先整理试验范围。',422)
    closed=[x for x in observed if x['state']=='closed'];known=[x for x in closed if x['net_realized'] is not None]
    all_known=bool(closed) and len(known)==len(closed)
    with localcontext() as ctx:
        ctx.prec=60;total=sum((Decimal(x['net_realized']) for x in known),Decimal('0'))
        positives=sum((max(Decimal('0'),Decimal(x['net_realized'])) for x in known),Decimal('0'))
        losses=sum((max(Decimal('0'),-Decimal(x['net_realized'])) for x in known),Decimal('0'))
        result={'experiment_id':record['id'],'protocol_hash':record['protocol_hash'],'observed_until':end.isoformat(),
            'sample_type':'prospectively_registered_observational','closed_count':len(closed),'open_count':len(observed)-len(closed),
            'known_net_count':len(known),'unknown_net_count':len(closed)-len(known),'net_realized':number(total) if all_known else None,
            'win_rate':number(Decimal(sum(Decimal(x['net_realized'])>0 for x in known))/len(known)) if known else None,
            'net_expectancy':number(total/len(known)) if all_known else None,'profit_factor':number(positives/losses) if all_known and losses else None,
            'sample_target':protocol['sample_target'],'target_reached':len(closed)>=protocol['sample_target'],'small_sample':len(closed)<30,
            'pre_recorded_plan_count':sum(x['pre_recorded_plan'] for x in observed),'observations':observed,'excluded':excluded,
            'cost_sensitivity':[{'additional_cost_per_roundtrip':v,'net_after_extra_cost':number(total-Decimal(v)*len(closed)) if all_known else None,
                'hypothetical':True} for v in protocol['additional_roundtrip_costs']],
            'edge_proven':False,'changes_risk':False,'backtest':False,
            'limitations':['前向登记的观察记录，不是受控实验或样本外回测；相符策略版本的盈利/亏损全部保留。',
                '后补或过期计划不能证明遵守规则；未归属交易另列，开放仓位和未知费用不混作完整样本。',
                '额外成本压力仅是假设敏感性，不修改实际费用；未计算参数重跑、未采用方案收益或因果归因。',
                '少量样本仅供探索；达到目标或30个样本也不能证明存在投资优势或授权增加风险。']}
        result['evaluation_hash']=digest(encoded({k:v for k,v in result.items() if k!='observed_until'}))
        result['archived_evaluation_outdated']=bool(record.get('evaluation_snapshot') and record['evaluation_snapshot']['evaluation_hash']!=result['evaluation_hash'])
        return result


def evaluate_experiment(store,object_id):
    with db.connect() as c:
        store.lock(c);return evaluate_in(store,c,store._get(c,'experiments',object_id))


def finish_experiment(store,object_id,version,decision,reason,evaluation_hash,key):
    if decision not in ('retain','reject','inconclusive','stopped') or not reason.strip() or len(reason)>3000:
        fail('invalid_experiment_decision','请选择保留/拒绝/无法判定/停止，并填写本人依据。',422)
    fingerprint=digest(encoded({'experiment_finish':object_id,'version':version,'decision':decision,'reason':reason,'hash':evaluation_hash}))
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        record=store._get(c,'experiments',object_id)
        if record['version']!=version or record['state']!='registered':fail('version_conflict','只有当前已登记试验可结项。')
        if decision!='stopped' and stamp(now())<stamp(record['end_at']):fail('experiment_not_ended','期间未结束时仅能记录停止，不能提前挑选结果结项。',422)
        evaluated=evaluate_in(store,c,record)
        if evaluation_hash!=evaluated['evaluation_hash']:fail('evaluation_changed','试验资料或账本已变化，请重新核对评价。')
        created=now();record={**record,'version':version+1,'state':'finished','finished_at':created,'updated_at':created,
            'decision':decision,'decision_reason':reason,'evaluation_snapshot':evaluated}
        store.save(c,'experiments',record);store.remember(c,key,fingerprint,record);return record


def list_experiments(store,account_id,page=1):
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        where="kind='experiments' AND data::jsonb->>'account_id'=?"
        total=c.execute('SELECT count(*) FROM investment_objects WHERE '+where,(account_id,)).fetchone()[0]
        rows=c.execute("SELECT (data::jsonb-'protocol_snapshot'-'evaluation_snapshot')::text FROM investment_objects WHERE "+where+' ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?',(account_id,(page-1)*50))
        return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'page_size':50}
