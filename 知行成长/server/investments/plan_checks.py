"""Manual evidence checks and deterministic sizing for a future conditional plan."""
from datetime import datetime, time
from decimal import Decimal, ROUND_FLOOR, localcontext
from zoneinfo import ZoneInfo

import db
from copilot.core import digest, encoded, fail, now
from .accounting import number
from .planning import policy_status_in

TZ=ZoneInfo('Asia/Shanghai')


def assess_plan(store,plan_id,as_of=None):
    with db.connect() as c:
        store.lock(c)
        return assess_in(store,c,store._get(c,'trade-plans',plan_id),as_of or now())


def assess_in(store,c,plan,as_of):
    if plan.get('intent','entry')!='entry':
        fail('research_only_plan','此处仅估算做多入场数量。退出/观察保留研究草稿；卖出需核对券商当前可卖数量。',422)
    stamp=datetime.fromisoformat(as_of).astimezone(TZ);day=stamp.date().isoformat()
    if not all(plan.get(k) is not None for k in ('planned_for','check_id','entry_price','invalidation_price','fee_budget','risk_budget','holding_sessions')):
        fail('execution_unverified','请补充核对资料、计划日期、进出价格、费用预算和持有期。',422)
    check=store._get(c,'plan-checks',plan['check_id'])
    instrument=store._get(c,'instruments',plan['instrument_id'])
    if check['instrument_id']!=plan['instrument_id'] or instrument['kind']=='fund':
        fail('invalid_plan_check','核对资料与计划证券不符；场外基金使用申请确认流程。',422)
    from .rules import compare_check, RULEBOOK_ID
    comparison=compare_check(instrument,check,plan['planned_for'],as_of)
    if check.get('rulebook_id') and (check['rulebook_id']!=RULEBOOK_ID or comparison['rules']['status']!='available' or comparison['calendar']['status']!='available'):
        fail('rule_reference_unavailable','自动核对依据过期、版本不符或无覆盖，请重新核对资料；不能沿用自动确认。',422)
    if comparison['mismatches']:
        fields='、'.join(m['field'] for m in comparison['mismatches'][:5])
        fail('rule_reference_mismatch','所填资料与公开规则/休市日历不一致：'+fields+'。请核对原文，实际已成交仍可如实记录。',422)
    sessions=check['sessions'];quote=datetime.fromisoformat(check['quote_as_of']).astimezone(TZ)
    target=plan['planned_for']
    expiry=datetime.fromisoformat(plan['valid_until']).astimezone(TZ)
    prior=[d for d,is_open in sessions.items() if is_open and (d<day or (d==day and stamp.time()>=time(15)))]
    if day not in sessions or quote>stamp or not prior or quote.date().isoformat()!=max(prior) or quote.time()<time(15):
        fail('stale_plan_check','盘后价格必须对应已核对日历内最近完成的开市日，不能采用未来或缺覆盖资料。',422)
    if target<day or (target==day and stamp.time()>=time(15)) or not sessions.get(target) or not check['rules_valid_from']<=day<=target<=check['rules_valid_until'] or not target<=expiry.date().isoformat()<=check['rules_valid_until'] or expiry<=stamp:
        fail('invalid_plan_session','请核对计划开市日、有效期与规则覆盖，休市或资料过期不能确认。',422)
    if check['trading_status']!='normal':
        fail('unknown_trading_status','交易状态非正常或未知，请先核对。',422)
    future=sorted(d for d,is_open in sessions.items() if is_open and d>=target)
    holding=plan['holding_sessions'];delay=check['sell_delay_sessions']
    if len(future)<max(holding,delay+1):
        fail('calendar_incomplete','日历未覆盖预计持有期与最早可卖日，不能按自然日代算。',422)
    if future[max(holding-1,delay)]>check['rules_valid_until']:
        fail('rule_coverage_incomplete','规则有效期未覆盖预计复核或最早可卖日，请补充核对资料。',422)
    capital=policy_status_in(store,c,plan['account_id'],target,plan['id'])
    if capital['conflicts'] or capital['available_after_buffer'] is None:
        fail('policy_conflict','请核对生效政策、现金缓冲、实际费用、暂停状态与单笔风险限制。',422)
    with localcontext() as ctx:
        ctx.prec=60
        entry=Decimal(plan['entry_price']);stop=Decimal(plan['invalidation_price']);fees=Decimal(plan['fee_budget'])
        tick=Decimal(check['price_tick']);step=Decimal(check['quantity_step']);risk=Decimal(plan['risk_budget'])
        if entry<=stop or entry%tick or stop%tick or risk<=fees:
            fail('invalid_plan_prices','做多计划入场价应高于失效价并符合本人核对的价格单位；风险预算须覆盖费用。',422)
        cash=Decimal(capital['available_after_buffer']);exposure_limit=capital['policy']['max_exposure']
        balance=store._balance(c,plan['account_id'],{})
        if exposure_limit is not None:
            if any(p['quantity']!='0' and p['instrument_id']!=plan['instrument_id'] for p in balance['positions']):
                fail('exposure_unverified','其他持仓缺当前估值，无法核对最大持仓金额。',422)
            current=sum((Decimal(p['quantity'])*Decimal(check['quote_price']) for p in balance['positions']),Decimal('0'))
            cash=min(cash,max(Decimal('0'),Decimal(exposure_limit)-current))
        raw=min((risk-fees)/(entry-stop),(cash-fees)/entry)
        maximum=comparison['rules']['rules'].get('maximum_quantity')
        if maximum is not None:raw=min(raw,Decimal(maximum))
        quantity=(raw/step).to_integral_value(rounding=ROUND_FLOOR)*step
        if quantity<Decimal(check['minimum_quantity']) or quantity<=0:
            fail('insufficient_plan_budget','按已知预算和数量单位无法形成一笔计划数量。',422)
        result={'quantity':number(quantity),'planned_loss':number(quantity*(entry-stop)+fees),
            'estimated_commitment':number(quantity*entry+fees),'risk_budget':plan['risk_budget'],
            'review_on':future[holding-1],'earliest_sell_on':future[delay],
            'check_snapshot':check,'policy_snapshot':capital['policy'],'as_of':as_of,
            'rule_comparison':comparison,
            'realtime':False,'mode':'user_checked_conditional','price_basis':'user_declared_post_close',
            'limitations':['资料由本人核对，系统未独立核验来源、行情或规则；这是未来条件计划，不是当前可成交承诺。',
                '费用预算为本人填写的本次进出合计估计；跳空、停牌、限价或无法成交可造成超预算损失。',
                '各计划不自动预留资金，若多个条件同时触发，须再次核对总暴露和可用现金。',
                '数量按价格差风险和现金缓冲取较小值，再按本人核对的数量单位向下取整；不自动增加风险。']}
        result['calculation_hash']=digest(encoded(result))
        return result
