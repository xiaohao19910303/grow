"""Bounded hypothetical bracket execution; declared inputs never establish a tradable edge."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from .accounting import number
from .replay import stamp, regular

MODEL_VERSION='next_open_stop_first_v1'

def execute_scenario(bars,check,daily,params):
    """One next-open entry attempt, stop-first bracket, no re-entry or forced liquidation."""
    with localcontext() as ctx:
        ctx.prec=60
        return _execute(bars,check,daily,params)


def _execute(bars,check,daily,p):
    cash=Decimal(p['cash']);held=cost=realized=commission_total=tax_total=Decimal('0')
    fills=[];events=[];entered=None;previous=None;stop_pending=False
    tick=Decimal(check['price_tick']);step=Decimal(check['quantity_step']);minimum=Decimal(check['minimum_quantity'])
    stop=Decimal(p['stop_price']);target=Decimal(p['target_price']);decision=stamp(p['decision_at'])
    rate=Decimal(p['commission_bps'])/10000;minimum_fee=Decimal(p['minimum_commission']);tax_rate=Decimal(p['sell_tax_bps'])/10000
    slip=Decimal(p['slippage_bps'])/10000;participation=Decimal(p['participation_rate'])
    def event(at,reason):events.append({'at':at,'reason':reason})
    def finish(status):
        return {'status':status,'cash':number(cash),'remaining_quantity':number(held),'remaining_cost':number(cost),
            'net_realized':number(realized) if status=='closed' else None,'known_partial_realized':number(realized),
            'commission_total':number(commission_total),'tax_total':number(tax_total),'fills':fills,'events':events,
            'hypothetical':True,'realtime':False,'point_in_time_verified':False,'edge_proven':False,
            'execution_model':MODEL_VERSION,'force_liquidation':False}
    def price(value,side):
        return (Decimal(value)*(1+slip if side=='buy' else 1-slip)/tick).to_integral_value(
            rounding=ROUND_CEILING if side=='buy' else ROUND_FLOOR)*tick
    def fee(value):return max(minimum_fee,value*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    def volume_cap(bar):return (Decimal(bar['volume_shares'])*participation/step).to_integral_value(rounding=ROUND_FLOOR)*step
    if stamp(p['evidence_available_at'])>decision:return finish('future_information')
    if check.get('sell_delay_sessions') is None:
        event(p['decision_at'],'sell_rule_unknown');return finish('unresolved')
    eligible=[b for b in bars if stamp(b['start'])>decision]
    if eligible:
        cursor=decision.replace(second=0,microsecond=0)+timedelta(minutes=1)
        while cursor<stamp(eligible[0]['start']):
            day=cursor.date().isoformat()
            if day not in check['sessions']:
                event(eligible[0]['start'],'calendar_unknown');return finish('unresolved')
            if check['sessions'][day] and regular(cursor):
                event(eligible[0]['start'],'missing_entry_minute');return finish('unresolved')
            cursor+=timedelta(minutes=1)
    for bar in eligible:
        at=stamp(bar['start']);day=at.date().isoformat();declared=daily.get(day)
        if held and previous:
            cursor=previous
            while cursor<at:
                gap_day=cursor.date().isoformat()
                if gap_day not in check['sessions']:
                    event(bar['start'],'calendar_unknown');return finish('unresolved')
                if check['sessions'][gap_day] and regular(cursor):
                    gap=daily.get(gap_day,{})
                    timely_halt=(gap.get('status')=='halted' and gap.get('available_at') and stamp(gap['available_at'])<=cursor
                        and gap.get('corporate_action')=='none_declared')
                    if not timely_halt:
                        event(bar['start'],'missing_held_minutes');return finish('unresolved')
                cursor+=timedelta(minutes=1)
        previous=stamp(bar['end'])
        if not check['rules_valid_from']<=day<=check['rules_valid_until'] or day not in check['sessions']:
            event(bar['start'],'rules_or_calendar_unknown');return finish('unresolved')
        if not check['sessions'][day] or not regular(at):
            event(bar['start'],'closed_session');return finish('unresolved')
        if not declared or not declared.get('available_at') or stamp(declared['available_at'])>at:
            event(bar['start'],'late_or_missing_constraints');return finish('unresolved')
        if declared['corporate_action']!='none_declared' or declared['status'] in ('unknown','delisted'):
            event(bar['start'],'corporate_action_or_identity_unknown');return finish('unresolved')
        if declared['status']=='halted':
            event(bar['start'],'halted')
            if not entered:return finish('entry_unfilled')
            continue
        if declared['limit_down'] is None or declared['limit_up'] is None:
            event(bar['start'],'price_limits_unknown');return finish('unresolved')
        lower,upper=Decimal(declared['limit_down']),Decimal(declared['limit_up'])
        high,low,opening=Decimal(bar['high']),Decimal(bar['low']),Decimal(bar['open'])
        if not lower<=low<=high<=upper or any(Decimal(bar[k])%tick for k in ('open','high','low','close')):
            event(bar['start'],'price_rule_conflict');return finish('unresolved')
        capacity=volume_cap(bar)
        if not entered:
            bought=price(opening,'buy')
            # Both fee regimes must fit: max(minimum commission, proportional commission).
            affordable=min((cash-minimum_fee)/bought,cash/(bought*(1+rate))) if bought>0 else Decimal('0')
            maximum=Decimal(check.get('maximum_quantity') or p['quantity'])
            quantity=(min(Decimal(p['quantity']),capacity,affordable,maximum)/step).to_integral_value(rounding=ROUND_FLOOR)*step
            if bought>=upper or bought>high or bought<low or quantity<minimum or not stop<bought<=target:
                event(bar['start'],'entry_price_liquidity_or_cash_unfilled');return finish('entry_unfilled')
            paid_fee=fee(bought*quantity)
            # Commission rounds to cents; an unrounded affordability estimate must not overdraw cash.
            if bought*quantity+paid_fee>cash:
                quantity-=step;paid_fee=fee(bought*quantity)
            if quantity<minimum:
                event(bar['start'],'entry_price_liquidity_or_cash_unfilled');return finish('entry_unfilled')
            held=quantity;cost=bought*quantity+paid_fee;cash-=cost;commission_total+=paid_fee;entered=day
            fills.append({'side':'buy','at':bar['start'],'price':number(bought),'quantity':number(quantity),'commission':number(paid_fee),'tax':'0'})
            # The full bar's volume cap is shared between entry and exit, never double consumed.
            capacity-=quantity
        touched_stop=low<=stop;double=touched_stop and high>=target
        if double:event(bar['start'],'same_bar_stop_first')
        exit_kind='pending_stop' if stop_pending else 'stop' if touched_stop else 'target' if high>target else None
        if touched_stop:stop_pending=True
        if exit_kind is None:continue
        first=stamp(entered+'T00:00:00+08:00').date();last=at.date()
        days=[(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
        if any(d not in check['sessions'] for d in days):
            event(bar['start'],'calendar_unknown');return finish('unresolved')
        if sum(check['sessions'][d] for d in days[1:])<check['sell_delay_sessions']:
            event(bar['start'],'sell_delay');continue
        base=opening if exit_kind=='pending_stop' else min(opening,stop) if exit_kind=='stop' else target
        sold=price(base,'sell')
        if sold<=lower or not low<=sold<=high:
            event(bar['start'],'limit_queue_unknown' if sold<=lower else 'slippage_outside_bar');continue
        quantity=min(held,capacity)
        if quantity<=0:
            event(bar['start'],'volume_unfilled');continue
        # Entry and minute capacity use the same declared quantity step.
        allocated=cost*quantity/held;commission=fee(sold*quantity)
        tax=(sold*quantity*tax_rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        proceeds=sold*quantity-commission-tax
        if cash+proceeds<0:
            event(bar['start'],'exit_fee_cash_unfilled');continue
        cash+=proceeds;realized+=proceeds-allocated;cost-=allocated;held-=quantity
        commission_total+=commission;tax_total+=tax
        fills.append({'side':'sell','at':bar['start'],'price':number(sold),'quantity':number(quantity),
            'commission':number(commission),'tax':number(tax),'reason':exit_kind})
        if not held:return finish('closed')
    return finish('open' if entered else 'no_entry_bar')
