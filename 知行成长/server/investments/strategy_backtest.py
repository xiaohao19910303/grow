"""Long-only event simulation: close-time signals, next-open execution and explicit rules."""
from datetime import datetime,date
from decimal import Decimal,localcontext,ROUND_FLOOR,ROUND_CEILING,ROUND_HALF_UP
from fractions import Fraction
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import Field,model_validator
from .contracts import Contract
from .rule_screening import finite


class BacktestConfig(Contract):
    initial_cash:str='100000'
    quantity:str='100'
    strategy:Literal['threshold','ma_cross']='ma_cross'
    entry_above:str|None=None
    exit_below:str|None=None
    fast_window:int=Field(default=5,ge=1,le=120)
    slow_window:int=Field(default=20,ge=2,le=250)
    lot_size:int=Field(default=100,ge=1,le=10000)
    price_tick:str='0.01'
    commission_rate:str='0.0003'
    minimum_commission:str='5'
    sell_tax_rate:str='0.0005'
    slippage_bps:str='10'
    max_participation:str='0.1'
    annual_periods:int=Field(default=252,ge=1,le=100000)
    annual_risk_free:str='0'
    @model_validator(mode='after')
    def valid(self):
        for field in ('initial_cash','quantity','price_tick'):
            if finite(getattr(self,field))<=0:raise ValueError('资金、数量和价格步长须为正。')
        if (Fraction(finite(self.quantity))/self.lot_size).denominator!=1:raise ValueError('数量须满足手数。')
        if finite(self.initial_cash)<Decimal('0.01') or not Decimal('0.000001')<=finite(self.price_tick)<=1000:raise ValueError('资金或价格步长超出模拟范围。')
        for field in ('commission_rate','minimum_commission','sell_tax_rate','slippage_bps'):
            if finite(getattr(self,field))<0:raise ValueError('成本不能为负。')
        if not 0<finite(self.max_participation)<=1 or finite(self.slippage_bps)>1000:raise ValueError('成交比例或滑点范围无效。')
        if finite(self.commission_rate)>1 or finite(self.sell_tax_rate)>1 or not -1<finite(self.annual_risk_free)<1:raise ValueError('费率范围无效。')
        if self.strategy=='ma_cross' and self.fast_window>=self.slow_window:raise ValueError('短均线须小于长均线。')
        if self.strategy=='threshold' and (self.entry_above is None or self.exit_below is None or min(finite(self.entry_above),finite(self.exit_below))<=0):raise ValueError('请填写正数买入与退出阈值。')
        return self


def number(value):
    return finite(value) if isinstance(value,str) else finite(str(value))


def text(value):
    if value is None:return None
    if value and (value.adjusted()>80 or value.adjusted() < -100):return None
    result=format(value,'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def metrics(points,initial,closed,costs,config,benchmark=None):
    values=[initial]+[Decimal(p['equity']) for p in points];last=values[-1]
    returns=[b/a-1 for a,b in zip(values,values[1:]) if a>0]
    n=len(returns);mean=sum(returns,Decimal(0))/n if n else None
    variance=sum(((r-mean)**2 for r in returns),Decimal(0))/(n-1) if n>1 else None
    sd=variance.sqrt() if variance is not None else None;period=Decimal(config.annual_periods)
    rf=(1+number(config.annual_risk_free))**(1/period)-1
    downside=(sum((min(r-rf,Decimal(0))**2 for r in returns),Decimal(0))/n).sqrt() if n else None
    peak=initial;drawdown=Decimal(0)
    for point in points:
        equity=Decimal(point['equity']);peak=max(peak,equity);decline=(equity/peak-1) if peak else Decimal(0)
        point['drawdown_pct']=text(decline*100);drawdown=min(drawdown,decline)
    wins=[c for c in closed if c['net']>0];losses=[c for c in closed if c['net']<0]
    annualized=None
    if n>1 and last>0:
        logarithm=(last/initial).ln()*period/n
        if abs(logarithm)<=100:annualized=text((logarithm.exp()-1)*100)
    return {'net_profit':text(last-initial),'total_return_pct':text((last/initial-1)*100),
        'annualized_return_pct':annualized,
        'maximum_drawdown_pct':text(-drawdown*100),'volatility_pct':text(sd*period.sqrt()*100) if sd is not None else None,
        'sharpe':text((mean-rf)/sd*period.sqrt()) if sd else None,
        'sortino':text((mean-rf)/downside*period.sqrt()) if downside and n>1 else None,
        'closed_round_trips':len(closed),'win_rate_pct':text(Decimal(len(wins))*100/len(closed)) if closed else None,
        'average_win':text(sum((c['net'] for c in wins),Decimal(0))/len(wins)) if wins else None,
        'average_loss':text(sum((c['net'] for c in losses),Decimal(0))/len(losses)) if losses else None,
        'largest_win':text(max((c['net'] for c in wins),default=None)),
        'largest_loss':text(min((c['net'] for c in losses),default=None)),
        'average_holding_calendar_days':text(Decimal(sum(c['days'] for c in closed))/len(closed)) if closed else None,
        'total_fees_and_tax':text(costs),'benchmark_return_pct':benchmark,
        'risk_metric_samples':n,'annual_periods':config.annual_periods,'annual_risk_free':config.annual_risk_free}


def backtest(series,config,start_at=None,end_at=None):
    """Inputs are declared historical facts, never inferred from a current market quote."""
    with localcontext() as ctx:
        ctx.prec=60
        return _run(series,config,start_at,end_at)


def _run(series,config,start_at,end_at):
    bars=series.get('bars',[]);missing=[]
    required=('time','open_at','available_at','open','high','low','close','volume_shares','suspended',
              'limit_up','limit_down','corporate_actions_known','adj_factor','split_ratio','cash_dividend')
    if not bars or len(bars)>10000:missing.append('bar_count')
    if series.get('price_basis')!='unadjusted':missing.append('unadjusted_prices_required')
    sessions=series.get('sessions')
    dates=set()
    last=None
    for i,bar in enumerate(bars):
        if not isinstance(bar,dict):missing.append(f'{i}:invalid_bar');continue
        absent=[f for f in required if bar.get(f) is None]
        if absent:missing.append(f'{i}:missing:'+','.join(absent));continue
        try:
            stamp=datetime.fromisoformat(bar['time']);opening=datetime.fromisoformat(bar['open_at']);available=datetime.fromisoformat(bar['available_at'])
            if any(t.tzinfo is None for t in (stamp,opening,available)) or opening>stamp or available<stamp:raise ValueError()
            if last is not None and stamp<=last:raise ValueError()
            last=stamp
            dates.add(stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
            if bar['corporate_actions_known'] is not True or type(bar['suspended']) is not bool:raise ValueError()
            for name in ('open','high','low','close','limit_up','limit_down','adj_factor','split_ratio'):
                if number(bar[name])<=0:raise ValueError()
            if number(bar['volume_shares'])<0 or number(bar['cash_dividend'])<0:raise ValueError()
            if not number(bar['low'])<=min(number(bar['open']),number(bar['close']))<=max(number(bar['open']),number(bar['close']))<=number(bar['high']):raise ValueError()
            if number(bar['limit_down'])>=number(bar['limit_up']):raise ValueError()
        except (ValueError,TypeError,ArithmeticError):missing.append(f'{i}:invalid_bar_or_rules')
    if not sessions or set(sessions)!=dates:missing.append('calendar_gaps')
    if series.get('interval')=='minute':
        try:
            expected=[datetime.fromisoformat(t) for t in series.get('expected_bar_times',[])]
            actual=[datetime.fromisoformat(b['time']) for b in bars]
            if not expected or any(t.tzinfo is None for t in expected) or len(set(expected))!=len(expected) or set(expected)!=set(actual):missing.append('minute_timeline_gaps_or_missing')
        except (ValueError,TypeError,KeyError):missing.append('minute_timeline_invalid')
    if missing:return {'status':'incomplete','missing':missing[:50],'metrics':None,'trades':[],'equity':[],'orders':[]}
    cash=number(config.initial_cash);initial=cash;quantity=Decimal(0);basis=Decimal(0);costs=Decimal(0)
    pending=None;opened=None;cycle_net=Decimal(0);trades=[];orders=[];points=[];closed=[];closes=[];availability=[];previous_mas=None
    begin=date.fromisoformat(start_at) if start_at else None;end=date.fromisoformat(end_at) if end_at else None
    for bar in bars:
        stamp=datetime.fromisoformat(bar['time']).astimezone(ZoneInfo('Asia/Shanghai'));opening=datetime.fromisoformat(bar['open_at']).astimezone(ZoneInfo('Asia/Shanghai'));available=datetime.fromisoformat(bar['available_at']);day=stamp.date()
        if end and day>end:break
        live=not begin or day>=begin
        price=number(bar['close']);adjusted=Fraction(price)*Fraction(number(bar['adj_factor']))
        if live and quantity:
            cash+=quantity*number(bar['cash_dividend']);cycle_net+=quantity*number(bar['cash_dividend'])
            quantity*=number(bar['split_ratio'])
            if quantity!=quantity.to_integral_value():
                return {'status':'incomplete','missing':['fractional_corporate_action_requires_cash_in_lieu'], 'metrics':None,'trades':trades,'orders':orders,'equity':points}
        if pending and live:
            side=pending['side'];reason=None;filled=Decimal(0);raw=number(bar['open']);volume=number(bar['volume_shares'])
            if datetime.fromisoformat(pending['signal_at'])>opening:reason='signal_not_known_at_open'
            elif bar['suspended']:reason='suspended'
            elif volume<=0:reason='no_volume'
            elif side=='sell' and opened and opening.date()<=opened.date():reason='t_plus_one'
            elif side=='buy' and raw>=number(bar['limit_up']):reason='limit_up'
            elif side=='sell' and raw<=number(bar['limit_down']):reason='limit_down'
            tick=number(config.price_tick);slip=number(config.slippage_bps)/10000
            execution=(raw*(1+slip if side=='buy' else 1-slip)/tick).to_integral_value(rounding=ROUND_CEILING if side=='buy' else ROUND_FLOOR)*tick
            if reason is None and (execution>number(bar['high']) or execution<number(bar['low']) or execution>number(bar['limit_up']) or execution<number(bar['limit_down'])):reason='slippage_outside_bar_or_limits'
            if reason is None:
                lot=Decimal(config.lot_size);capacity=(volume*number(config.max_participation)/lot).to_integral_value(rounding=ROUND_FLOOR)*lot
                wanted=number(config.quantity) if side=='buy' else quantity
                if side=='buy':
                    upper=int(min(wanted,capacity,(cash/execution/lot).to_integral_value(rounding=ROUND_FLOOR)*lot)/lot)
                    low=0
                    while low<upper:
                        candidate=(low+upper+1)//2;gross=execution*lot*candidate
                        charge=max(number(config.minimum_commission),gross*number(config.commission_rate)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
                        if gross+charge<=cash:low=candidate
                        else:upper=candidate-1
                    filled=Decimal(low)*lot
                else:filled=min(wanted,capacity if capacity<quantity else quantity)
                if filled<=0:reason='cash_or_participation_limit'
            if reason is None:
                gross=execution*filled
                fee=max(number(config.minimum_commission),gross*number(config.commission_rate)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
                tax=(gross*number(config.sell_tax_rate)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) if side=='sell' else Decimal(0)
                if side=='buy':
                    cash-=gross+fee;quantity+=filled;basis=gross+fee;opened=opening;cycle_net=-(gross+fee)
                else:
                    cash+=gross-fee-tax;allocated=basis*filled/quantity;basis-=allocated;quantity-=filled;cycle_net+=gross-fee-tax
                    if quantity==0:
                        closed.append({'net':cycle_net,'days':(opening.date()-opened.date()).days});opened=None;basis=Decimal(0)
                costs+=fee+tax
                trades.append({'side':side,'time':bar['open_at'],'signal_at':pending['signal_at'],'price':text(execution),'quantity':text(filled),
                    'fee':text(fee),'tax':text(tax),'cash_after':text(cash),'position_after':text(quantity)})
            orders.append({**pending,'execution_at':bar['open_at'],'status':'filled' if reason is None else 'rejected','reason':reason or 'next_open','filled_quantity':text(filled)})
            pending=None
        closes.append(adjusted)
        availability.append(available)
        if live:
            points.append({'time':bar['time'],'equity':text(cash+quantity*price),'cash':text(cash),'quantity':text(quantity),'close':bar['close']})
            enter=exit=False
            if not bar['suspended']:
                if config.strategy=='threshold':enter=price>number(config.entry_above);exit=price<number(config.exit_below)
                elif len(closes)>=config.slow_window:
                    fast=sum(closes[-config.fast_window:])/config.fast_window;slow=sum(closes[-config.slow_window:])/config.slow_window
                    known=max(availability[-config.slow_window:])
                    if known<=available and previous_mas and previous_mas[2]<=available:
                        enter=previous_mas[0]<=previous_mas[1] and fast>slow;exit=previous_mas[0]>=previous_mas[1] and fast<slow
                    previous_mas=(fast,slow,known)
            if quantity==0 and enter:pending={'side':'buy','signal_at':bar['available_at'],'signal_bar':bar['time']}
            elif quantity>0 and exit:pending={'side':'sell','signal_at':bar['available_at'],'signal_bar':bar['time']}
        elif config.strategy=='ma_cross' and len(closes)>=config.slow_window:
            previous_mas=(sum(closes[-config.fast_window:])/config.fast_window,sum(closes[-config.slow_window:])/config.slow_window,max(availability[-config.slow_window:]))
    if pending:orders.append({**pending,'status':'unexecuted','reason':'no_next_open','filled_quantity':'0'})
    return {'status':'complete','missing':[],'algorithm':'next-open-long-only-v1','execution_assumptions':'declared point-in-time rules; no shorting or forced final liquidation',
        'final_cash':text(cash),'open_quantity':text(quantity),'open_cost_basis':text(basis),'trades':trades,'orders':orders,'equity':points,
        'metrics':metrics(points,initial,closed,costs,config),
        'limitations':['输入的历史时点、公司行动和交易状态按本人来源声明，软件不构成独立真实性核验。','未平仓按末次收盘估值；费用与年化周期为本次配置假设。']}
