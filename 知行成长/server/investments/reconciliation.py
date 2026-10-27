"""Explicit unresolved facts invalidate derived assurances, never rewrite ledger facts."""
import json
from datetime import datetime


def notices(c,account_id,as_of=None):
    records=[json.loads(r[0]) for r in c.execute("SELECT data FROM investment_objects WHERE kind='ledger-notices' AND data::jsonb->>'account_id'=?",(account_id,))]
    result=[]
    for record in records:
        if as_of:
            cutoff=datetime.fromisoformat(as_of)
            if datetime.fromisoformat(record['created_at'])>cutoff:continue
            if datetime.fromisoformat(record['updated_at'])>cutoff:
                row=c.execute("SELECT data FROM investment_versions WHERE object_id=? AND (data::jsonb->>'updated_at')::timestamptz<=?::timestamptz ORDER BY version DESC LIMIT 1",(record['id'],as_of)).fetchone()
                record=json.loads(row[0])
            if datetime.fromisoformat(record['observed_at'])>cutoff:continue
        if record['status']=='open':result.append(record)
    return result


def apply_notices(c,account_id,balance,as_of=None):
    active=notices(c,account_id,as_of)
    affected={n['instrument_id'] for n in active}
    for position in balance['positions']:
        position['quantity_verified']=position['instrument_id'] not in affected
        if position['instrument_id'] in affected:
            position.update(cost=None,realized=None,unrealized=None)
    balance['reconciliation_notices']=active
    if active:
        balance.update(realized=None,net_realized=None,equity=None,cash_verified=False)
        balance['warnings'].append('存在公司行动或账实差异待核对，所录数量不代表已核验实际持仓，相关成本/净结果和可用现金暂不可确认。')
    return balance
