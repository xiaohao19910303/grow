"""Explicit confirmations append versions; a draft never masquerades as executable."""
from datetime import datetime

import db
from copilot.core import digest, encoded, fail, now


def transition(store,kind,object_id,version,state,key):
    if kind not in ('policies','strategies','trade-plans'):
        fail('invalid_transition','此记录不支持计划状态操作。',422)
    if state not in ('confirmed','declined','expired','cancelled','paused'):
        fail('invalid_transition','无效的计划状态。',422)
    fingerprint=digest(encoded({'transition':kind,'id':object_id,'version':version,'state':state}))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        old=store._get(c,kind,object_id)
        if old['version']!=version:
            fail('version_conflict','计划已更新，请核对最新版本。')
        if state=='confirmed':
            if old['state']!='draft':
                fail('invalid_transition','只有草稿可以确认，请先创建修改版本。')
            if kind=='strategies' and not all(old.get(k) for k in ('entry_conditions','exit_conditions','validation_scope')):
                fail('incomplete_strategy','请补充策略入场、退出和验证范围。',422)
            if kind=='policies' and not all(old.get(k) for k in ('purpose','liquidity_needs','loss_capacity')):
                fail('incomplete_policy','请补充资金用途、用钱需求和损失承受能力。',422)
            if kind=='trade-plans':
                missing=[k for k in ('strategy_id','rationale','entry_conditions','invalidation','risk_budget','holding_sessions') if not old.get(k)]
                if missing:
                    fail('incomplete_plan','计划尚缺策略、理由、触发/失效、预算或持有期。',422)
                if datetime.fromisoformat(old['valid_until'])<=datetime.fromisoformat(now()):
                    fail('expired_plan','计划已过有效期。',422)
                strategy=store._get(c,'strategies',old['strategy_id'])
                if strategy.get('state')!='confirmed':
                    fail('unconfirmed_strategy','请先确认策略版本。',422)
                # P0 does not infer current trading rules or quotes from a manual symbol.
                fail('execution_unverified','交易规则与行情时点尚未核验；草稿已保留，可继续研究。',422)
        stamp=now()
        record={**old,'version':version+1,'state':state,'updated_at':stamp}
        if state=='confirmed':
            record['confirmed_at']=stamp
        store.save(c,kind,record)
        store.remember(c,key,fingerprint,record)
        return record
