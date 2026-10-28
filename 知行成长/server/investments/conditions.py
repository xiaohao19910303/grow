"""Deterministic offline condition drills. No realtime feed, scheduler or notifications."""
import json
from datetime import date, timedelta, time
from decimal import Decimal
from typing import Literal

import db
from pydantic import AwareDatetime, Field, StrictBool, model_validator
from copilot.core import digest, encoded, fail, now
from .contracts import Contract, Identifier, Positive
from .replay import stamp, TZ
from .rules import compare_check


class ConditionInput(Contract):
    account_id: Identifier
    path_id: Identifier
    check_id: Identifier
    title: str = Field(min_length=1,max_length=160)
    op: Literal['gte','lte']
    threshold: Positive
    intent: Literal['observe','entry','exit'] = 'observe'
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    assumed_bought_on: date | None = None
    max_age_seconds: int = Field(default=60,ge=1,le=300,strict=True)
    arrival_delay_seconds: int = Field(default=0,ge=0,le=3600,strict=True)
    notification_scope: Literal['none','page'] = 'none'
    probe_at: list[AwareDatetime] = Field(default_factory=list,max_length=10)
    acknowledged: StrictBool

    @model_validator(mode='after')
    def bounded_window(self):
        if not self.acknowledged or self.valid_until<=self.valid_from or self.valid_until-self.valid_from>timedelta(days=62):
            raise ValueError('请确认离线演练，期间须顺序且不超过62天。')
        if self.intent=='exit' and (self.assumed_bought_on is None or self.assumed_bought_on>self.valid_from.astimezone(TZ).date()):
            raise ValueError('退出演练须填写不晚于开始日的假设买入日。')
        return self


def evaluate_tick(rule,check,reference,at,quote,seen):
    """One declared observation at a simulated arrival clock; seen is local to this drill."""
    clock=stamp(at);day=clock.date().isoformat()
    result={'at':clock.isoformat(),'quote_as_of':quote['as_of'] if quote else None,
        'price':quote['price'] if quote else None,'realtime':False,'executable':False,'page_candidate':False}
    def state(value):return {**result,'status':value}
    if clock<stamp(rule['valid_from']):return state('not_started')
    if clock>=stamp(rule['valid_until']):return state('expired')
    if reference['conflicts']:return state('rule_conflict')
    if not reference['rules_available']:return state('rules_unknown')
    if not reference.get('valid_from','0001-01-01')<=day<=reference.get('valid_until','9999-12-31'):
        return state('rules_expired')
    if not check['rules_valid_from']<=day<=check['rules_valid_until']:return state('rules_expired')
    sessions=check['sessions']
    if day not in sessions:return state('calendar_unknown')
    if not sessions[day]:return state('closed_session')
    if not (time(9,30)<=clock.time()<time(11,30) or time(13)<=clock.time()<time(15)):
        return state('outside_session')
    if check['trading_status']!='normal':return state('trading_status_unknown')
    if quote is None:return state('missing_quote')
    quoted=stamp(quote['as_of']);age=(clock-quoted).total_seconds()
    if age<0:return state('future_quote')
    if quoted.date()!=clock.date() or age>rule['max_age_seconds']:return state('stale')
    if Decimal(quote['volume'])<=0:return state('no_trades')
    if rule['intent']=='exit':
        delay=check.get('sell_delay_sessions');bought=rule['assumed_bought_on']
        if delay is None:return state('sell_rule_unknown')
        first=date.fromisoformat(bought);last=clock.date()
        if last<first or (last-first).days>369:return state('calendar_unknown')
        days=[(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
        if any(d not in sessions for d in days):return state('calendar_unknown')
        if not sessions[bought]:return state('invalid_buy_session')
        if sum(sessions[d] for d in days[1:])<delay:return state('sell_delay')
    price,threshold=Decimal(quote['price']),Decimal(rule['threshold'])
    matched=price>=threshold if rule['op']=='gte' else price<=threshold
    if not matched:return state('not_met')
    if day in seen:return state('duplicate_suppressed')
    seen.add(day)
    result['page_candidate']=rule['notification_scope']=='page'
    return state('matched')


def run_drill(store,payload,key):
    rule=ConditionInput.model_validate(payload).model_dump(mode='json')
    fingerprint=digest(encoded({'condition_drill':rule}));rid='drill-'+fingerprint
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        store._get(c,'accounts',rule['account_id']);path=store._get(c,'intraday-paths',rule['path_id'])
        check=store._get(c,'plan-checks',rule['check_id'])
        if path['account_id']!=rule['account_id'] or path['instrument_id']!=check['instrument_id']:
            fail('scope_mismatch','演练路径、账户与本人核对资料的证券必须一致。',422)
        existing=c.execute("SELECT data FROM investment_objects WHERE id=? AND kind='condition-drills'",(rid,)).fetchone()
        if existing:
            record=json.loads(existing[0]);store.remember(c,key,fingerprint,record);return record
        created=now();clock=stamp(created)
        if stamp(rule['valid_until'])>clock or any(stamp(t)>clock for t in rule['probe_at']):
            fail('future_drill','离线演练的结束和检查时点不能晚于当前时间。',422)
        instrument=store._get(c,'instruments',path['instrument_id'])
        comparison=compare_check(instrument,check,stamp(rule['valid_from']).date().isoformat(),created)
        reference={'rules_available':comparison['rules']['status']=='available' and comparison['calendar']['status']=='available',
            'conflicts':bool(comparison['mismatch_count']),
            'valid_from':comparison['rules']['effective_from'],'valid_until':comparison['rules']['review_until']}
        # Each completed minute is visible only at its declared end plus the simulated delay.
        arrivals=[]
        for bar in path['bars']:
            end=stamp(bar['end']);arrival=end+timedelta(seconds=rule['arrival_delay_seconds'])
            if stamp(rule['valid_from'])<=arrival<stamp(rule['valid_until']):
                arrivals.append((arrival,{'as_of':bar['end'],'price':bar['close'],'volume':bar['volume_shares']}))
        # Probes use only observations that have arrived; expiry is explicit even with no new quote.
        events=[(at,0,q) for at,q in arrivals]
        events.extend((stamp(t),1,None) for t in rule['probe_at'])
        events.append((stamp(rule['valid_until']),1,None));events.sort(key=lambda e:(e[0],e[1]))
        latest=None;seen=set();rows=[]
        for at,kind,quote in events:
            if kind==0:latest=quote
            rows.append(evaluate_tick(rule,check,reference,at.isoformat(),latest,seen))
        counts={status:sum(r['status']==status for r in rows) for status in sorted({r['status'] for r in rows})}
        record={'id':rid,'version':1,'created_at':created,'updated_at':created,'account_id':rule['account_id'],
            'instrument_id':path['instrument_id'],'rule_snapshot':rule,'check_snapshot':check,'reference_snapshot':comparison,
            'path_id':path['id'],'path_hash':path['snapshot_hash'],'source_label':path['source_label'],
            'rows':rows,'status_counts':counts,'matched_count':counts.get('matched',0),
            'page_candidate_count':sum(r['page_candidate'] for r in rows),'realtime':False,'executable':False,
            'notification_sent':False,'mode':'offline_condition_drill',
            'limitations':['使用本人声明分钟收盘和模拟到达时钟；不是实时提醒、回测或当时可知证明。',
                '仅核对明确的价格阈值，不解释计划中的自由文本；不评估预算、委托队列或真实可卖数量。',
                '状态、日历和回转间隔来自本人核对资料及公开参考子集；ETF不从名称推定T+0。',
                '同次演练每交易日最多一条模拟提示；再次跌破后回到阈值不重复提示。不同演练独立。',
                '仅在本页面展示模拟提示；不发送系统/站外通知，网页关闭后没有后台检查或通知。',
                '缺段不插值；主动检查时才判定断流。演练到期明确标记过期，不承诺实时定时降级。']}
        record['result_hash']=digest(encoded(record));store.save(c,'condition-drills',record,fresh=True)
        store.remember(c,key,fingerprint,record);return record


def list_drills(store,account_id,page=1):
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        where="kind='condition-drills' AND data::jsonb->>'account_id'=?"
        total=c.execute('SELECT count(*) FROM investment_objects WHERE '+where,(account_id,)).fetchone()[0]
        rows=c.execute("SELECT (data::jsonb-'rows'-'check_snapshot'-'reference_snapshot')::text FROM investment_objects WHERE "+where+
            ' ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?',(account_id,(page-1)*50))
        return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'page_size':50}
