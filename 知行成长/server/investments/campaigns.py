"""Derived trade cycles: one open cycle per account/instrument, immutable fill snapshots."""
from decimal import Decimal, localcontext

from .accounting import number, reconcile


def freeze_entry_risk(fill):
    """Bind actual entry quantity/price to the pre-entry stop, never the whole cash budget."""
    plan=fill.get('plan_snapshot') or {}
    if fill['side']!='buy' or not fill.get('plan_valid_at_execution') or not all(plan.get(k) is not None for k in ('invalidation_price','fee_budget')):
        return None
    if not plan.get('assessment_snapshot',{}).get('quantity'):
        return None
    with localcontext() as ctx:
        ctx.prec=60
        entry,stop,quantity=Decimal(fill['price']),Decimal(plan['invalidation_price']),Decimal(fill['quantity'])
        if entry<=stop:return None
        return {'plan_id':plan['id'],'plan_version':plan['version'],'entry_price':fill['price'],
            'invalidation_price':plan['invalidation_price'],'quantity':fill['quantity'],
            'price_risk':number((entry-stop)*quantity),'fee_budget':plan['fee_budget'],
            'planned_quantity':plan['assessment_snapshot']['quantity'],'declared_risk_limit':plan['risk_budget'],
            'formula':'实际入场价格与事前失效价格之差乘实际数量；同计划版本的进出费用预算在交易链只计一次。'}


def project(account,fills):
    with localcontext() as ctx:
        ctx.prec=60
        return _project(account,fills)


def _project(account,fills):
    current={}
    cycles=[]
    for opening in account['opening_positions']:
        item={'id':'opening-'+account['id']+'-'+opening['instrument_id'],
              'instrument_id':opening['instrument_id'],'opened_at':account['baseline_date'],
              'opening_positions':[opening],'fills':[],'quantity':Decimal(opening['quantity'])}
        current[opening['instrument_id']]=item
        cycles.append(item)
    for fill in fills:
        instrument=fill['instrument_id']
        if instrument not in current:
            item={'id':'campaign-'+fill['id'],'instrument_id':instrument,'opened_at':fill['executed_at'],
                  'opening_positions':[],'fills':[],'quantity':Decimal('0')}
            current[instrument]=item
            cycles.append(item)
        item=current[instrument]
        item['fills'].append(fill)
        item['quantity']+=Decimal(fill['quantity'])*(1 if fill['side']=='buy' else -1)
        if item['quantity']==0:
            item['closed_at']=fill['executed_at']
            del current[instrument]
    result=[]
    for cycle in cycles:
        accounting=reconcile('0',[],cycle['fills'],opening_positions=cycle['opening_positions'])
        budgets={};price_risks=[];limits={}
        planned_quantities={}
        risk_known=not cycle['opening_positions']
        for fill in cycle['fills']:
            if fill['side']!='buy':
                continue
            snapshot=fill.get('initial_risk_snapshot')
            if not snapshot or fill.get('risk_snapshot_invalidated'):
                risk_known=False
            else:
                key=(snapshot['plan_id'],snapshot['plan_version'])
                price_risks.append(Decimal(snapshot['price_risk']));budgets[key]=Decimal(snapshot['fee_budget'])
                limits[key]=Decimal(snapshot['declared_risk_limit'])
                planned_quantities[key]=planned_quantities.get(key,Decimal('0'))+Decimal(snapshot['quantity'])
                if planned_quantities[key]>Decimal(snapshot['planned_quantity']):risk_known=False
        risk=sum(price_risks,Decimal('0'))+sum(budgets.values(),Decimal('0')) if risk_known else None
        pnl=accounting['net_realized']
        closed=cycle['quantity']==0
        result.append({'id':cycle['id'],'account_id':account['id'],'instrument_id':cycle['instrument_id'],
            'state':'closed' if closed else 'open','opened_at':cycle['opened_at'],
            'closed_at':cycle.get('closed_at'),'quantity':number(cycle['quantity']),
            'fill_ids':[f['id'] for f in cycle['fills']], 'fills':cycle['fills'],
            'net_realized':pnl,'risk_basis':number(risk),
            'risk_basis_kind':'frozen_actual_entry_risk','risk_limit_exceeded':None if risk is None else risk>sum(limits.values(),Decimal('0')),
            'risk_basis_note':'冻结各批实际入场价格/数量与事前失效价；同计划版本进出费用预算只计一次。实际入场事实被更正、超出确认数量或无事前依据时不计算R；不是最大损失保证。',
            'realized_r':number(Decimal(pnl)/risk) if closed and pnl is not None and risk and risk>0 else None,
            'fees_complete':accounting['fees_complete'],
            'cost':accounting['positions'][0]['cost'] if accounting['positions'] else None})
    return result
