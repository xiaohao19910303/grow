"""Derived trade cycles: one open cycle per account/instrument, immutable fill snapshots."""
from decimal import Decimal

from .accounting import number, reconcile


def project(account,fills):
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
        budgets={}
        risk_known=not cycle['opening_positions']
        for fill in cycle['fills']:
            if fill['side']!='buy':
                continue
            plan=fill.get('plan_snapshot')
            if not plan or not fill.get('plan_recorded_before_execution') or not plan.get('risk_budget'):
                risk_known=False
            else:
                budgets[(plan['id'],plan['version'])]=Decimal(plan['risk_budget'])
        risk=sum(budgets.values(),Decimal('0')) if risk_known else None
        pnl=accounting['net_realized']
        closed=cycle['quantity']==0
        result.append({'id':cycle['id'],'account_id':account['id'],'instrument_id':cycle['instrument_id'],
            'state':'closed' if closed else 'open','opened_at':cycle['opened_at'],
            'closed_at':cycle.get('closed_at'),'quantity':number(cycle['quantity']),
            'fill_ids':[f['id'] for f in cycle['fills']], 'fills':cycle['fills'],
            'net_realized':pnl,'risk_basis':number(risk),
            'realized_r':number(Decimal(pnl)/risk) if closed and pnl is not None and risk and risk>0 else None,
            'fees_complete':accounting['fees_complete'],
            'cost':accounting['positions'][0]['cost'] if accounting['positions'] else None})
    return result
