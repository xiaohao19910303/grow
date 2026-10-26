"""Whitelist-only, three-valued conditions over the user's cached instrument universe."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

import db
from pydantic import Field, model_validator
from .contracts import Contract
from .providers import indicators
from .accounting import number
from copilot.core import fail


class Condition(Contract):
    field: Literal['market','kind','name','close','close_change_pct','turnover_cny','volume_ratio_5','price_above_ma20']
    op: Literal['eq','ne','gt','gte','lt','lte','contains']
    value: str = Field(max_length=100)

    @model_validator(mode='after')
    def valid_comparison(self):
        if self.field in ('market','kind','name'):
            if self.op not in ('eq','ne','contains'):
                raise ValueError('文本字段只支持等于、不等于或包含。')
        elif self.field=='price_above_ma20':
            if self.op not in ('eq','ne') or self.value not in ('true','false'):
                raise ValueError('均线比较使用true/false。')
        else:
            try:
                value=Decimal(self.value)
                if self.op=='contains' or not value.is_finite() or abs(value)>Decimal('1e20'):
                    raise ValueError()
            except (InvalidOperation,ValueError):
                raise ValueError('无效数值比较。')
        return self


class ScreenInput(Contract):
    as_of: date
    conditions: list[Condition] = Field(default_factory=list,max_length=10)
    combine: Literal['all','any'] = 'all'
    sort_by: Literal['close','close_change_pct','turnover_cny','volume_ratio_5'] = 'turnover_cny'
    descending: bool = True
    limit: int = Field(default=50,ge=1,le=100)


def matches(actual,condition):
    if actual is None:
        return None
    if condition.field in ('market','kind','name'):
        if condition.op not in ('eq','ne','contains'):
            fail('invalid_condition','文本字段只支持等于、不等于或包含。',422)
        return actual==condition.value if condition.op=='eq' else actual!=condition.value if condition.op=='ne' else condition.value in actual
    if condition.field=='price_above_ma20':
        if condition.value not in ('true','false') or condition.op not in ('eq','ne'):
            fail('invalid_condition','均线比较使用true/false和等于/不等于。',422)
        result=actual==(condition.value=='true')
        return result if condition.op=='eq' else not result
    if condition.op=='contains':
        fail('invalid_condition','数值字段不支持包含。',422)
    try:
        left,right=Decimal(str(actual)),Decimal(condition.value)
        if not left.is_finite() or not right.is_finite():
            raise ValueError()
    except (InvalidOperation,ValueError):
        fail('invalid_condition','筛选阈值必须是有限十进制数。',422)
    return {'eq':left==right,'ne':left!=right,'gt':left>right,'gte':left>=right,'lt':left<right,'lte':left<=right}[condition.op]


def filter_snapshots(universe,request):
    selected=[];unresolved=0
    for item in universe:
        bars=sorted([b for b in item['bars'] if b['date']<=request.as_of.isoformat()],key=lambda b:b['date'])
        latest=bars[-1] if bars else None
        metrics=indicators(bars)
        values={k:item[k] for k in ('name','market','kind')}
        values.update({'close':latest['close'] if latest else None,
            'turnover_cny':latest['turnover_cny'] if latest else None,'volume_ratio_5':metrics['volume_ratio_5'],
            'price_above_ma20':Decimal(latest['close'])>Decimal(metrics['ma20']) if latest and metrics['ma20'] is not None else None,
            'close_change_pct':number((Decimal(bars[-1]['close'])/Decimal(bars[-2]['close'])-1)*100) if len(bars)>1 and Decimal(bars[-2]['close'])>0 else None})
        outcomes=[matches(values[c.field],c) for c in request.conditions]
        if not bars:
            unresolved+=1
            continue
        accepted=not outcomes or (all(x is True for x in outcomes) if request.combine=='all' else any(x is True for x in outcomes))
        if not accepted and any(x is None for x in outcomes):
            unresolved+=1
        if accepted:
            selected.append({'instrument_id':item['instrument_id'],'name':item['name'],'code':item.get('code'),
                'market':item['market'],'kind':item['kind'],'data_date':latest['date'],
                'retrieved_at':item.get('retrieved_at'),'provider':item.get('provider'),
                'snapshot_id':item.get('snapshot_id'),'values':values,'condition_results':outcomes})
    known=[r for r in selected if r['values'][request.sort_by] is not None]
    missing=[r for r in selected if r['values'][request.sort_by] is None]
    known.sort(key=lambda r:Decimal(r['values'][request.sort_by]),reverse=request.descending)
    ordered=known+missing
    return {'items':ordered[:request.limit],'total':len(ordered),'universe_count':len(universe),'unresolved':unresolved,
        'scope':'private_cached_universe','full_market':False,'as_of':request.as_of.isoformat(),
        'conditions':request.model_dump(mode='json'),
        'limitations':['仅筛选本账号已缓存标的，不代表全市场。无数据或指标不足不视为满足条件。',
            '收盘变化和均线基于未复权有效记录，除权/停牌等情况须核对。',
            '历史日期筛选不证明资料当时已可获得，不作为历史回测结果。']}


def screen(store,request):
    with db.connect() as c:
        instruments={row['id']:row for row in [json.loads(r[0]) for r in c.execute("SELECT data FROM investment_objects WHERE kind='instruments'")]}
        rows=c.execute("""SELECT DISTINCT ON (data::jsonb->>'instrument_id') data FROM investment_objects
            WHERE kind='market-snapshots' ORDER BY data::jsonb->>'instrument_id',created_at DESC,id DESC LIMIT 2001""").fetchall()
        if len(rows)>2000:
            fail('screen_scope_too_large','本地筛选覆盖已超出首版限制，请缩小数据范围。',422)
        universe=[]
        for row in rows:
            snapshot=json.loads(row[0]);instrument=instruments.get(snapshot['instrument_id'])
            if instrument:
                universe.append({**instrument,'instrument_id':instrument['id'],'bars':snapshot['bars'],
                    'retrieved_at':snapshot['retrieved_at'],'provider':snapshot['provider'],'snapshot_id':snapshot['id']})
        return filter_snapshots(universe,request)
