"""Reproducible ledger-only period metrics and original-decision comparisons."""
import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import db
from copilot.core import fail
from .accounting import reconcile, number
from .campaigns import project

TZ=ZoneInfo('Asia/Shanghai')


def day_of(stamp):
    return datetime.fromisoformat(stamp).astimezone(TZ).date().isoformat()


def records(c,kind,account_id):
    return [json.loads(r[0]) for r in c.execute("SELECT data FROM investment_objects WHERE kind=? AND data::jsonb->>'account_id'=? ORDER BY created_at,id",(kind,account_id))]


def ordered_fills(c,account_id):
    return [json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_fills f JOIN investment_objects o ON o.id=f.id
        WHERE f.account_id=? ORDER BY f.executed_at,f.sequence''',(account_id,))]


def campaign_detail(store,account_id,campaign_id):
    with db.connect() as c:
        store.lock(c);store._get(c,'accounts',account_id)
        campaign=next((v for v in store._campaigns(c,account_id) if v['id']==campaign_id),None)
        if not campaign:fail('not_found','交易链不存在。',404)
        fills=[{'fill':f,'original_plan':f.get('plan_snapshot'),'original_strategy':f.get('strategy_snapshot'),
            'plan_status':'before_execution' if f.get('plan_recorded_before_execution') else 'retrospective' if f.get('plan_snapshot') else 'absent'} for f in campaign['fills']]
        return {'campaign':campaign,'fills':fills,'reviews':[r for r in records(c,'reviews',account_id) if r.get('campaign_id')==campaign_id],
            'limitations':['盈亏与判断正确、遵守规则分别评价；事后补记不作为事前合规证据。','当前无持有期间完整行情路径，不计算MAE/MFE。']}


def period_summary(store,account_id,start,end):
    try:
        first,last=date.fromisoformat(start),date.fromisoformat(end)
        if last<first or (last-first).days>3660:raise ValueError()
    except (ValueError,TypeError):fail('invalid_period','请选择开始不晚于结束、最长10年的期间。',422)
    with db.connect() as c,localcontext() as ctx:
        ctx.prec=60;store.lock(c);account=store._get(c,'accounts',account_id)
        if start<account['baseline_date']:fail('before_baseline','此期间早于核对起点，历史绩效不可推算。',422)
        fills=ordered_fills(c,account_id);events=records(c,'cash-events',account_id)
        prior=[f for f in fills if day_of(f['executed_at'])<start]
        through=[f for f in fills if day_of(f['executed_at'])<=end]
        prior_events=[e for e in events if day_of(e['occurred_at'])<start]
        through_events=[e for e in events if day_of(e['occurred_at'])<=end]
        before=reconcile(account['opening_cash'],prior_events,prior,opening_positions=account['opening_positions'])
        after=reconcile(account['opening_cash'],through_events,through,opening_positions=account['opening_positions'])
        cycles=project(account,through)
        from .reconciliation import notices
        unresolved=[n for n in notices(c,account_id) if day_of(n['observed_at'])<=end]
        affected={n['instrument_id'] for n in unresolved}
        if affected:
            after.update(net_realized=None,equity=None,cash_verified=False)
            for position in after['positions']:
                if position['instrument_id'] in affected:position.update(quantity_verified=False,cost=None,realized=None,unrealized=None)
            for cycle in cycles:
                if cycle['instrument_id'] in affected:cycle.update(net_realized=None,realized_r=None)
        closed=[v for v in cycles if v['state']=='closed' and start<=day_of(v['closed_at'])<=end]
        opened=[v for v in cycles if v['state']=='open']
        known=[v for v in closed if v['net_realized'] is not None]
        wins=sum(Decimal(v['net_realized'])>0 for v in known)
        r_values=[v['realized_r'] for v in closed if v['realized_r'] is not None]
        groups={}
        for cycle in closed:
            strategies={(f.get('strategy_snapshot',{}).get('id'),f.get('strategy_snapshot',{}).get('version')) for f in cycle['fills'] if f['side']=='buy'}
            name=next(iter(strategies)) if len(strategies)==1 and next(iter(strategies))[0] else ('mixed_or_unplanned',None)
            groups.setdefault(name,[]).append(cycle)
        group_results=[{'strategy_id':k[0],'strategy_version':k[1],
            'strategy_title':next((f['strategy_snapshot']['title'] for x in v for f in x['fills'] if f.get('strategy_snapshot',{}).get('id')==k[0]),'混合策略或无计划'),
            'closed_count':len(v),'known_net_count':sum(x['net_realized'] is not None for x in v),
            'net_realized':number(sum((Decimal(x['net_realized']) for x in v),Decimal('0'))) if all(x['net_realized'] is not None for x in v) else None} for k,v in groups.items()]
        period_events=[e for e in through_events if day_of(e['occurred_at'])>=start]
        amounts={kind:number(sum((Decimal(e['amount']) for e in period_events if e['kind']==kind),Decimal('0'))) for kind in ('deposit','withdrawal','dividend','interest','fee')}
        fees_complete=before['fees_complete'] and after['fees_complete']
        net=number(Decimal(after['net_realized'])-Decimal(before['net_realized'])) if before['net_realized'] is not None and after['net_realized'] is not None else None
        reviews=[r for r in records(c,'reviews',account_id) if start<=r['date']<=end]
        recommendations=records(c,'recommendations',account_id)
        decisions={r.get('id'):r for r in recommendations}
        suggestions=[]
        if c.execute("SELECT to_regclass('investment_analysis_jobs')").fetchone()[0]:
            for row in c.execute("SELECT data FROM investment_analysis_jobs WHERE state='ready'"):
                job=json.loads(row[0]);preview=store._get(c,'analysis-previews',job['preview_id'])
                if preview.get('account_id')!=account_id or not start<=day_of(job['created_at'])<=end:continue
                for index,suggestion in enumerate(job['report']['suggestions']):
                    decision=decisions.get('recommendation-'+job['id']+'-'+str(index),{})
                    suggestions.append({'job_id':job['id'],'index':index,'title':suggestion['title'],'state':decision.get('state','pending'),
                        'valid_until':suggestion['valid_until'],'outcome':'unresolved','linked_id':decision.get('linked_id')})
        return {'account_id':account_id,'start':start,'end':end,'timezone':'Asia/Shanghai','net_realized':net,**amounts,
            'fees_complete':fees_complete,'fill_count':sum(start<=day_of(f['executed_at'])<=end for f in through),
            'closed_count':len(closed),'known_net_closed_count':len(known),'open_count':len(opened),
            'win_rate':number(Decimal(wins)/len(known)) if known else None,'win_rate_denominator':len(known),
            'r_sample_count':len(r_values),'average_r':number(sum((Decimal(v) for v in r_values),Decimal('0'))/len(r_values)) if r_values else None,
            'cash_at_end':after['cash'],'cash_verified':after['cash_verified'],'positions_at_end':after['positions'],
            'strategy_groups':group_results,'reviews':reviews,'suggestions':suggestions,'drawdown':None,'twr':None,'xirr':None,
            'reconciliation_required':bool(unresolved),
            'formulas':{'net_realized':'期末累计成交已实现净盈亏 - 期初前累计成交已实现净盈亏；仅含成交内费用，不含浮盈、入出金、分红、利息或单列账户费用',
                'win_rate':'期间平仓且净盈亏已知的盈利交易链数 / 净盈亏已知的期间平仓交易链数；零结果计入分母',
                'average_r':'期间平仓且事前风险基数已知的R均值；未知不补零'},
            'limitations':['费用、基金实际净额或历史成本不完整时净结果显示未知；现金也可能为暂估。',
                '仅按期间内平仓统计胜率，开放仓位另列；少数交易不能证明策略有效。',
                '没有逐日估值和资金流时间序列，不计算回撤、TWR、XIRR或持有路径指标。',
                '策略归组依据成交冻结版本；多策略混合或无计划单列。AI建议全量保留，未实现影子收益核验，不混入实盘。']}
