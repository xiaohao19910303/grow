"""Private immutable execution studies on declared paths, separate from production backtests."""
import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

import db
from pydantic import AwareDatetime, Field, StrictBool, StringConstraints, ValidationError, model_validator
from copilot.core import digest, encoded, fail, now
from .contracts import Contract, Identifier, Money, Positive
from .replay import stamp
from .rules import compare_check, RULEBOOK_ID
from .execution import execute_scenario, MODEL_VERSION


class ExecutionInput(Contract):
    account_id: Identifier
    path_id: Identifier
    check_id: Identifier
    title: str = Field(min_length=1,max_length=160)
    decision_at: AwareDatetime
    evidence_available_at: AwareDatetime
    cash: Positive
    quantity: Positive
    stop_price: Positive
    target_price: Positive
    commission_bps: Money = Field(le=10000)
    minimum_commission: Money = Field(le=100000)
    sell_tax_bps: Money = Field(le=10000)
    slippage_bps: Money = Field(le=1000)
    participation_rate: Positive = Field(le=1)
    constraints_text: Annotated[str,StringConstraints(strip_whitespace=False)] = Field(min_length=1,max_length=30000)
    source_note: str = Field(min_length=1,max_length=2000)
    acknowledged: StrictBool

    @model_validator(mode='after')
    def confirmed(self):
        if not self.acknowledged or self.stop_price>=self.target_price:
            raise ValueError('请确认假设模型，失效价须低于目标价。')
        return self


class DailyConstraint(Contract):
    date: date
    status: Literal['normal','halted','delisted','unknown']
    limit_down: Positive | None
    limit_up: Positive | None
    available_at: AwareDatetime | None
    corporate_action: Literal['none_declared','unknown','adjustment_required']

    @model_validator(mode='after')
    def limits(self):
        if self.limit_down is not None and self.limit_up is not None and self.limit_down>=self.limit_up:
            raise ValueError('上下限须顺序。')
        return self


def parse_constraints(text):
    if len(text.encode('utf-8'))>30000:fail('invalid_execution_constraints','每日状态CSV不能超过30KB。',422)
    result={}
    try:
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        fields={'date','status','limit_down','limit_up','available_at','corporate_action'}
        if set(reader.fieldnames or [])!=fields or len(reader.fieldnames)!=len(fields):raise ValueError()
        for i,row in enumerate(reader):
            if i>=63:raise ValueError()
            for key in ('limit_down','limit_up','available_at'):
                if row.get(key)=='':row[key]=None
            item=DailyConstraint.model_validate(row).model_dump(mode='json');day=item.pop('date')
            if day in result:raise ValueError()
            result[day]=item
        if not result:raise ValueError()
    except (ValueError,TypeError,csv.Error,ValidationError):
        fail('invalid_execution_constraints','请核对逐日状态CSV的六列、唯一日期、含时区资料时点、价格上下限与公司行动声明；未知留空或标unknown。',422)
    return result


def run_study(store,payload,key):
    data=ExecutionInput.model_validate(payload).model_dump(mode='json')
    fingerprint=digest(encoded({'execution_study':data,'model_version':MODEL_VERSION}));rid='study-'+fingerprint
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        store._get(c,'accounts',data['account_id']);path=store._get(c,'intraday-paths',data['path_id'])
        check=store._get(c,'plan-checks',data['check_id'])
        if path['account_id']!=data['account_id'] or path['instrument_id']!=check['instrument_id']:
            fail('scope_mismatch','撮合路径、账户与核对资料须对应同一证券。',422)
        existing=c.execute("SELECT data FROM investment_objects WHERE id=? AND kind='execution-studies'",(rid,)).fetchone()
        if existing:
            record=json.loads(existing[0]);store.remember(c,key,fingerprint,record);return record
        created=now();first=stamp(path['bars'][0]['start']);last=stamp(path['bars'][-1]['end']);decision=stamp(data['decision_at'])
        if last-first>timedelta(days=62) or not first-timedelta(days=7)<=decision<last or decision>stamp(created):
            fail('invalid_execution_window','路径最多62天，假设决策须在路径结束前、开始前7天以内且不在未来。',422)
        if Decimal(data['stop_price'])%Decimal(check['price_tick']) or Decimal(data['target_price'])%Decimal(check['price_tick']):
            fail('invalid_execution_tick','失效价和目标价须符合所选资料的价格单位。',422)
        daily=parse_constraints(data['constraints_text'])
        instrument=store._get(c,'instruments',path['instrument_id'])
        comparison=compare_check(instrument,check,first.date().isoformat(),created)
        execution_check={**check,'maximum_quantity':comparison['rules']['rules'].get('maximum_quantity')}
        result=execute_scenario(path['bars'],execution_check,daily,data)
        if (comparison['mismatch_count'] or comparison['rules']['status']!='available' or comparison['calendar']['status']!='available'
            or last.date().isoformat()>comparison['rules']['review_until'] or check.get('rulebook_id') not in (None,RULEBOOK_ID)):
            # Never publish hypothetical P&L when the public subset contradicts the supplied model.
            result={'status':'unresolved_reference','net_realized':None,'remaining_quantity':None,'remaining_cost':None,
                'cash':data['cash'],'known_partial_realized':None,'commission_total':None,'tax_total':None,'fills':[],
                'events':[{'at':data['decision_at'],'reason':'public_reference_unavailable_or_conflicting'}],
                'hypothetical':True,'realtime':False,'point_in_time_verified':False,'edge_proven':False,
                'execution_model':MODEL_VERSION,'force_liquidation':False}
        record={'id':rid,'version':1,'created_at':created,'updated_at':created,'account_id':data['account_id'],
            'instrument_id':path['instrument_id'],'input_snapshot':data,'check_snapshot':check,'reference_snapshot':comparison,
            'path_id':path['id'],'path_hash':path['snapshot_hash'],'source_label':path['source_label'],
            'daily_constraints':daily,'result':result,'mode':'declared_execution_study','production_backtest':False,
            'limitations':['本人声明路径及每日状态的假设撮合，未独立验证历史时点、退市覆盖或复权；不能证明历史策略收益。',
                '只尝试决策之后下一普通竞价分钟开盘入场；缺该分钟不跳到后续赢家。一次开仓、可分批退出，不重开、不强制平仓。',
                '同分钟双触发先按失效处理；T+1或无法成交时保留失效退出意图，之后按首个可行分钟开盘尝试。',
                '费用显式填写，佣金和卖出税按每笔四舍五入至分；滑点按不利方向取整至价格单位。',
                '每分钟量占比仅为假设容量上限，入场与退出共享；涨停买入/跌停卖出队列不明不撮合，不能保证真实成交。',
                '未复权路径遇公司行动未知或须调整、退市状态或持有分钟缺失，整体净结果为空，不编造退出价。',
                '单证券单场景，没有历史成分全样本、自动信号、参数搜索或样本外验证，不自动改变计划/风险/账本。']}
        record['result_hash']=digest(encoded(record));store.save(c,'execution-studies',record,fresh=True)
        store.remember(c,key,fingerprint,record);return record


def list_studies(store,account_id,page=1):
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        where="kind='execution-studies' AND data::jsonb->>'account_id'=?"
        total=c.execute('SELECT count(*) FROM investment_objects WHERE '+where,(account_id,)).fetchone()[0]
        rows=c.execute("SELECT jsonb_build_object('id',id,'title',data::jsonb->'input_snapshot'->'title','created_at',created_at,'status',data::jsonb->'result'->'status')::text FROM investment_objects WHERE "+where+
            ' ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?',(account_id,(page-1)*50))
        return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'page_size':50}
