"""Explicit confirmations append versions; a draft never masquerades as executable."""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import db
from copilot.core import digest, encoded, fail, now


def transition(store,kind,object_id,version,state,key,reason=''):
    if kind not in ('policies','strategies','trade-plans','period-plans'):
        fail('invalid_transition','此记录不支持计划状态操作。',422)
    if state not in ('confirmed','declined','expired','cancelled','paused','untriggered','skipped'):
        fail('invalid_transition','无效的计划状态。',422)
    if state in ('untriggered','skipped') and (not reason.strip() or kind not in ('trade-plans','period-plans')):
        fail('missing_state_reason','请为未触发或主动跳过的计划留下原因。',422)
    command={'transition':kind,'id':object_id,'version':version,'state':state}
    if reason:command['reason']=reason
    fingerprint=digest(encoded(command))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        old=store._get(c,kind,object_id)
        if old['version']!=version:
            fail('version_conflict','计划已更新，请核对最新版本。')
        if old['state']==state:
            fail('invalid_transition','当前已经是此状态。',422)
        if state=='confirmed':
            if old['state']!='draft':
                fail('invalid_transition','只有草稿可以确认，请先创建修改版本。')
            if kind=='strategies' and not all(old.get(k) for k in ('entry_conditions','exit_conditions','validation_scope')):
                fail('incomplete_strategy','请补充策略入场、退出和验证范围。',422)
            if kind=='period-plans':
                if not old.get('check_id') or not old.get('focus'):
                    fail('incomplete_period_plan','请填写关注事项和已核对日历。',422)
                check=store._get(c,'plan-checks',old['check_id'])
                dates=[(date.fromisoformat(old['period_start'])+timedelta(days=i)).isoformat()
                    for i in range((date.fromisoformat(old['period_end'])-date.fromisoformat(old['period_start'])).days+1)]
                if any(d not in check['sessions'] for d in dates) or old['period_end']<datetime.fromisoformat(now()).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat():
                    fail('calendar_incomplete','日历缺少计划期间或计划已结束，请重新核对。',422)
                session_dates=[d for d in dates if check['sessions'][d]]
                if not session_dates and not old['no_trade']:
                    fail('closed_period','计划期间均为休市，仅能确认不交易的观察计划。',422)
            if kind=='policies' and not all(old.get(k) for k in ('purpose','liquidity_needs','loss_capacity')):
                fail('incomplete_policy','请补充资金用途、用钱需求和损失承受能力。',422)
            if kind=='policies':
                import json
                for row in c.execute("""SELECT DISTINCT ON (v.object_id) v.data FROM investment_versions v
                    JOIN investment_objects o ON o.id=v.object_id WHERE o.kind='policies'
                    AND v.data::jsonb->>'account_id'=? AND v.data::jsonb->>'state' IS NOT NULL AND v.data::jsonb->>'state'<>'draft'
                    ORDER BY v.object_id,v.version DESC""",(old['account_id'],)):
                    other=json.loads(row[0])
                    if other['state'] in ('confirmed','paused') and other['id']!=old['id'] and other['period_start']<=old['period_end'] and old['period_start']<=other['period_end']:
                        fail('overlapping_policy','此期间已有生效资金政策，请修改原政策版本或选择其他期间。',422)
            if kind=='trade-plans':
                status=policy_status_in(store,c,old['account_id'],datetime.fromisoformat(now()).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),object_id)
                if status['conflicts']:
                    fail('policy_conflict','资金政策缺失、暂停新增风险或超过预算，请先核对。',422)
                missing=[k for k in ('strategy_id','rationale','entry_conditions','invalidation','risk_budget','holding_sessions') if not old.get(k)]
                if missing:
                    fail('incomplete_plan','计划尚缺策略、理由、触发/失效、预算或持有期。',422)
                if datetime.fromisoformat(old['valid_until'])<=datetime.fromisoformat(now()):
                    fail('expired_plan','计划已过有效期。',422)
                strategy=store._get(c,'strategies',old['strategy_id'])
                if strategy.get('state')!='confirmed':
                    fail('unconfirmed_strategy','请先确认策略版本。',422)
                from .plan_checks import assess_in
                assessment=assess_in(store,c,old,now())
        stamp=now()
        record={**old,'version':version+1,'state':state,'updated_at':stamp}
        if reason:record['state_reason']=reason
        if state=='confirmed':
            record['confirmed_at']=stamp
            if kind=='trade-plans':
                record['assessment_snapshot']=assessment
                record['strategy_snapshot']=strategy
            if kind=='period-plans':
                record['calendar_snapshot']=check
                record['session_dates']=session_dates
        store.save(c,kind,record)
        store.remember(c,key,fingerprint,record)
        return record


def effective_policies(c,account_id,as_of):
    """A saved draft does not revoke a previously confirmed policy version."""
    import json
    rows=c.execute("""SELECT DISTINCT ON (v.object_id) v.data FROM investment_versions v
        JOIN investment_objects o ON o.id=v.object_id WHERE o.kind='policies'
        AND v.data::jsonb->>'account_id'=? AND v.data::jsonb->>'state' IS NOT NULL AND v.data::jsonb->>'state'<>'draft'
        AND (v.data::jsonb->>'updated_at')::timestamptz < (?::date + interval '1 day') AT TIME ZONE 'Asia/Shanghai'
        ORDER BY v.object_id,v.version DESC""",(account_id,as_of)).fetchall()
    policies=[p for p in (json.loads(r[0]) for r in rows) if p['state'] in ('confirmed','paused') and p['period_start']<=as_of<=p['period_end']]
    return [{**p,'pause_new_risk':True} if p['state']=='paused' else p for p in policies]


def policy_status(store,account_id,as_of,plan_id=None):
    from datetime import date
    with db.connect() as c:
        store.lock(c);store._get(c,'accounts',account_id)
        return policy_status_in(store,c,account_id,date.fromisoformat(as_of).isoformat(),plan_id)


def policy_status_in(store,c,account_id,as_of,plan_id=None):
    import json
    from decimal import Decimal
    from .accounting import number
    policies=effective_policies(c,account_id,as_of)
    policy=policies[0] if len(policies)==1 else None
    conflicts=[]
    if len(policies)>1:
        conflicts.append('ambiguous_policy')
    if not policy:
        conflicts.append('missing_effective_policy')
    # Current cash is explicitly not an historical balance projection.
    balance=store._balance(c,account_id,{})
    deposits=withdrawals=Decimal('0')
    if policy:
        for row in c.execute("SELECT data FROM investment_objects WHERE kind='cash-events' AND data::jsonb->>'account_id'=?",(account_id,)):
            event=json.loads(row[0]);day=datetime.fromisoformat(event['occurred_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            if policy['period_start']<=day<=min(as_of,policy['period_end']):
                if event['kind']=='deposit':deposits+=Decimal(event['amount'])
                if event['kind']=='withdrawal':withdrawals+=Decimal(event['amount'])
        if policy['pause_new_risk']:conflicts.append('new_risk_paused')
    if plan_id:
        plan=store._get(c,'trade-plans',plan_id)
        if plan['account_id']!=account_id:
            fail('scope_mismatch','计划不属于当前投资账户。',422)
        if policy and plan.get('risk_budget') is not None and policy['trade_risk_budget'] is not None and Decimal(plan['risk_budget'])>Decimal(policy['trade_risk_budget']):
            conflicts.append('risk_budget_exceeded')
    available=None
    if policy and policy['cash_buffer'] is not None and balance['cash_verified']:
        available=max(Decimal('0'),Decimal(balance['cash'])-Decimal(policy['cash_buffer']))
    return {'policy':policy,'conflicts':conflicts,'as_of':as_of,'actual_deposit':number(deposits),'actual_withdrawal':number(withdrawals),
        'deposit_gap':number(deposits-Decimal(policy['planned_deposit'])) if policy else None,
        'withdrawal_gap':number(withdrawals-Decimal(policy['planned_withdrawal'])) if policy else None,
        'available_after_buffer':number(available),'cash_basis':'current_ledger_not_historical',
        'limitations':['拟入出金不是实际流水；可用现金仅按当前账本与已知费用估算，未预留外部未成交委托。',
            '持仓估值、总风险与亏损复核线缺少行情时不自动判断。']}
