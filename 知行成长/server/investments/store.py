"""Transactional private records, immutable versions and replay-safe writes."""
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import db
from pydantic import ValidationError

from copilot.core import digest, encoded, fail, now
from .accounting import reconcile
from .contracts import RESOURCE_MODELS
from .observable_conditions import UnverifiableCondition
from .schema import TABLES


class InvestmentStore:
    startup_error = None

    def initialize(self):
        with db.connect() as c:
            c.executescript(TABLES)

    @staticmethod
    def lock(c):
        # One write lock per private schema, valid across processes and HTTP retries.
        c.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),hashtext('investments'))")

    @staticmethod
    def validate(kind, data):
        model = RESOURCE_MODELS.get(kind)
        if model is None:
            fail('not_found', '投资记录类型不存在。', 404)
        try:
            return model.model_validate(data).model_dump(mode='json')
        except ValidationError as exc:
            # 条件校验只返回固定说明，便于修改草稿；不回显输入或其他校验上下文。
            for error in exc.errors(include_input=False):
                cause=error.get('ctx',{}).get('error')
                if isinstance(cause,UnverifiableCondition):
                    fail('unverifiable_conditions',str(cause),422)
            fail('validation_error', '请核对必填字段、十进制字符串和带时区的时间。', 422)

    @staticmethod
    def _get(c, kind, object_id):
        row = c.execute('SELECT data FROM investment_objects WHERE id=? AND kind=?', (object_id,kind)).fetchone()
        if not row:
            fail('not_found', '投资记录不存在。', 404)
        return json.loads(row[0])

    def get(self, kind, object_id):
        with db.connect() as c:
            return self._get(c, kind, object_id)

    def listing(self, kind, *, page=1, page_size=50, account_id=None):
        if kind not in RESOURCE_MODELS:
            fail('not_found', '投资记录类型不存在。', 404)
        page, page_size = max(1,page), min(100,max(1,page_size))
        with db.connect() as c:
            where, args = 'kind=?', [kind]
            if account_id:
                self._get(c,'accounts',account_id)
                where += " AND data::jsonb->>'account_id'=?"
                args.append(account_id)
            total = c.execute('SELECT count(*) FROM investment_objects WHERE '+where,args).fetchone()[0]
            projection="(data::jsonb-'source_snapshots')::text" if kind in ('dossiers','principles') else 'data'
            rows = c.execute('SELECT '+projection+' FROM investment_objects WHERE '+where+
                ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', [*args,page_size,(page-1)*page_size]).fetchall()
            return {'items':[json.loads(r[0]) for r in rows], 'total':total,'page':page,'page_size':page_size}

    def history(self, kind, object_id):
        with db.connect() as c:
            self._get(c,kind,object_id)
            return [json.loads(r[0]) for r in c.execute(
                'SELECT data FROM investment_versions WHERE object_id=? ORDER BY version',(object_id,))]

    @staticmethod
    def replay(c, key, fingerprint):
        if not isinstance(key,str) or not key or len(key)>160:
            fail('validation_error','缺少有效的请求编号。',422)
        old = c.execute('SELECT fingerprint,response FROM investment_requests WHERE request_key=?',(key,)).fetchone()
        if old:
            if old[0] != fingerprint:
                fail('conflict','相同请求编号对应了不同内容，请核对原请求。')
            return json.loads(old[1])

    @staticmethod
    def remember(c,key,fingerprint,response):
        c.execute('INSERT INTO investment_requests VALUES (?,?,?)',(key,fingerprint,encoded(response)))

    @staticmethod
    def save(c, kind, data, *, fresh=False):
        if fresh:
            c.execute('INSERT INTO investment_objects VALUES (?,?,?,?,?,?)',
                (data['id'],kind,data['version'],encoded(data),data['created_at'],data['updated_at']))
        else:
            c.execute('UPDATE investment_objects SET version=?,data=?,updated_at=? WHERE id=?',
                (data['version'],encoded(data),data['updated_at'],data['id']))
        c.execute('INSERT INTO investment_versions VALUES (?,?,?)',(data['id'],data['version'],encoded(data)))

    def references(self,c,kind,data):
        account = self._get(c,'accounts',data['account_id']) if data.get('account_id') else None
        if data.get('instrument_id'):
            self._get(c,'instruments',data['instrument_id'])
        for opening in data.get('opening_positions',[]):
            self._get(c,'instruments',opening['instrument_id'])
        if len({p['instrument_id'] for p in data.get('opening_positions',[])}) != len(data.get('opening_positions',[])):
            fail('validation_error','期初同一证券请合并为一条持仓。',422)
        if data.get('strategy_id'):
            self._get(c,'strategies',data['strategy_id'])
        if data.get('check_id'):
            check=self._get(c,'plan-checks',data['check_id'])
            if data.get('instrument_id') and check['instrument_id']!=data['instrument_id']:
                fail('scope_mismatch','核对资料与计划标的不一致。',422)
        if kind in ('fills','cash-events'):
            stamp = datetime.fromisoformat(data['executed_at'] if kind=='fills' else data['occurred_at'])
            if stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() < account['baseline_date']:
                fail('validation_error','发生时间不能早于账户核对基准日。',422)
        if kind == 'policies' and data['period_end'] < data['period_start']:
            fail('validation_error','政策结束日期不能早于开始日期。',422)
        if data.get('plan_id'):
            plan = self._get(c,'trade-plans',data['plan_id'])
            if (plan['account_id'],plan['instrument_id']) != (data['account_id'],data['instrument_id']):
                fail('validation_error','成交与计划的账户或证券不一致。',422)
        if kind=='fills' and data.get('plan_version') is not None and not data.get('plan_id'):
            fail('validation_error','指定计划版本时必须先选择关联计划。',422)
        if data.get('campaign_id'):
            if not any(item['id']==data['campaign_id'] for item in self._campaigns(c,data['account_id'])):
                fail('not_found','关联交易链不存在或已需重新核对。',404)
        for source_kind,field in [('research','evidence_ids'),('reviews','source_review_ids')]:
            for source_id in data.get(field,[]):
                source=self._get(c,source_kind,source_id)
                if source.get('account_id') not in (None,data.get('account_id')) or (kind=='dossiers' and source.get('instrument_id') not in (None,data['instrument_id'])):
                    fail('scope_mismatch','引用来源不属于当前投资账户或证券。',422)

    def create(self,kind,payload,key):
        data = self.validate(kind,payload)
        if kind=='cash-events' and data['kind'].startswith('fund_receivable_'):
            fail('invalid_cash_event','基金待到账流水由确认/到账操作生成，不能独立添加。',422)
        if kind=='fills' and data['source']=='fund_confirmation':
            fail('fund_confirmation_required','基金确认成交由专用申请确认流程生成。',422)
        fingerprint = digest(encoded({'kind':kind,'data':data}))
        with db.connect() as c:
            self.lock(c)
            return self.create_in(c,kind,data,key,fingerprint)

    def create_in(self,c,kind,data,key,fingerprint=None):
        fingerprint = fingerprint or digest(encoded({'kind':kind,'data':data}))
        old = self.replay(c,key,fingerprint)
        if old is not None:
            return old
        self.references(c,kind,data)
        if kind=='instruments':
            row=c.execute("SELECT data FROM investment_objects WHERE kind='instruments' AND data::jsonb->>'market'=? AND data::jsonb->>'code'=?",
                          (data['market'],data['code'])).fetchone()
            if row:
                existing=json.loads(row[0])
                if existing['kind']!=data['kind']:
                    fail('instrument_conflict','同一市场和代码已登记为其他品种，请核对。')
                self.remember(c,key,fingerprint,existing)
                return existing
        if kind=='fills' and data.get('external_id'):
            row = c.execute('SELECT id FROM investment_fills WHERE account_id=? AND source=? AND external_id=?',
                (data['account_id'],data['source'],data['external_id'])).fetchone()
            if row:
                existing=self._get(c,'fills',row[0])
                if any(existing.get(k)!=v for k,v in data.items()):
                    fail('conflict','外部成交编号已存在，但内容不同，请核对。')
                self.remember(c,key,fingerprint,existing)
                return existing
        stamp=now()
        record={**data,'id':'inv-'+uuid.uuid4().hex,'version':1,'created_at':stamp,'updated_at':stamp}
        if kind=='research':record['evidence_hash']=digest(encoded(data))
        if kind in ('dossiers','principles'):
            source_kind,field=('research','evidence_ids') if kind=='dossiers' else ('reviews','source_review_ids')
            record['source_snapshots']=[self._get(c,source_kind,i) for i in data[field]]
        if kind=='fills' and data.get('plan_id'):
            plan=self._get(c,'trade-plans',data['plan_id'])
            if data.get('plan_version') is not None:
                row=c.execute('SELECT data FROM investment_versions WHERE object_id=? AND version=?',
                    (plan['id'],data['plan_version'])).fetchone()
                if not row:fail('not_found','指定计划版本不存在。',404)
                plan=json.loads(row[0])
            else:
                # Late recording can still bind the version known at the execution time.
                row=c.execute("""SELECT data FROM investment_versions WHERE object_id=?
                    AND data::jsonb->>'state'='confirmed' AND (data::jsonb->>'confirmed_at')::timestamptz<=?::timestamptz
                    ORDER BY version DESC LIMIT 1""",(plan['id'],data['executed_at'])).fetchone()
                if row:plan=json.loads(row[0])
            record['plan_snapshot']=plan
            if plan.get('strategy_snapshot'):
                record['strategy_snapshot']=plan['strategy_snapshot']
            record['plan_recorded_before_execution']=(plan.get('state')=='confirmed' and
                datetime.fromisoformat(plan['confirmed_at'])<=datetime.fromisoformat(data['executed_at']))
            execution=datetime.fromisoformat(data['executed_at'])
            record['plan_valid_at_execution']=(record['plan_recorded_before_execution'] and execution<=datetime.fromisoformat(plan['valid_until']) and
                bool(plan.get('planned_for')) and execution.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()>=plan['planned_for'])
        if kind=='fills':
            from .campaigns import freeze_entry_risk
            record['initial_risk_snapshot']=freeze_entry_risk(record)
        if kind in ('policies','strategies','trade-plans','period-plans','principles'):
            record['state']='draft'
        if kind=='fund-orders':
            instrument=self._get(c,'instruments',data['instrument_id'])
            if instrument['kind']!='fund':
                fail('validation_error','此申请仅适用于场外基金。',422)
            if (data['side']=='subscription' and not data.get('amount')) or (data['side']=='redemption' and not data.get('quantity')):
                fail('validation_error','申购请填写金额，赎回请填写份额。',422)
            record['state']='pending'
        self.save(c,kind,record,fresh=True)
        if kind=='accounts':
            c.execute('INSERT INTO investment_accounts VALUES (?,?,?)',
                (record['id'],record['opening_cash'],record['baseline_date']))
        elif kind=='fills':
            c.execute('''INSERT INTO investment_fills
                (id,account_id,instrument_id,side,price,quantity,fee,tax,executed_at,source,external_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',tuple(record[k] for k in ('id','account_id','instrument_id',
                'side','price','quantity','fee','tax','executed_at','source','external_id')))
            try:
                self._balance(c,record['account_id'],{})
            except ValueError as exc:
                fail('reconciliation_required',str(exc),422)
        elif kind=='cash-events':
            c.execute('INSERT INTO investment_cash_events VALUES (?,?,?,?,?)',tuple(record[k]
                for k in ('id','account_id','kind','amount','occurred_at')))
        self.remember(c,key,fingerprint,record)
        return record


    def update(self,kind,object_id,version,payload,key):
        fingerprint=digest(encoded({'kind':kind,'id':object_id,'version':version,'data':payload}))
        with db.connect() as c:
            self.lock(c)
            replay=self.replay(c,key,fingerprint)
            if replay is not None:
                return replay
            old=self._get(c,kind,object_id)
            if old['version']!=version:
                fail('version_conflict','记录已更新，请载入最新版本后再修改。')
            if kind not in ('policies','strategies','trade-plans','reviews','period-plans','watchlist','dossiers','principles','ledger-notices'):
                fail('immutable_fact','此事实需通过专用核对流程更正，不能覆盖。')
            previous={k:old[k] for k in RESOURCE_MODELS[kind].model_fields if k in old}
            data=self.validate(kind,{**previous,**payload})
            self.references(c,kind,data)
            if old.get('account_id') != data.get('account_id'):
                fail('validation_error','已有记录不能移到另一个账户。',422)
            record={**data,'id':object_id,'version':version+1,'created_at':old['created_at'],'updated_at':now()}
            if kind in ('dossiers','principles'):
                source_kind,field=('research','evidence_ids') if kind=='dossiers' else ('reviews','source_review_ids')
                record['source_snapshots']=[self._get(c,source_kind,i) for i in data[field]]
            if 'state' in old:
                record['state']='draft'
            self.save(c,kind,record)
            self.remember(c,key,fingerprint,record)
            return record

    def _balance(self,c,account_id,marks,as_of=None):
        account=self._get(c,'accounts',account_id)
        if as_of and datetime.fromisoformat(account['created_at'])>datetime.fromisoformat(as_of):
            fail('future_information','账户核对信息在分析截止时间之后才录入，请调整截止时间。',422)
        fill_filter=' AND f.executed_at<=?::timestamptz AND o.created_at<=?::timestamptz' if as_of else ''
        event_filter=' AND e.occurred_at<=?::timestamptz AND o.created_at<=?::timestamptz' if as_of else ''
        fills=[json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_fills f
            JOIN investment_objects o ON o.id=f.id WHERE f.account_id=?'''+fill_filter+' ORDER BY f.executed_at,f.sequence',
            (account_id,as_of,as_of) if as_of else (account_id,))]
        if as_of:
            for index,fill in enumerate(fills):
                if datetime.fromisoformat(fill['updated_at'])>datetime.fromisoformat(as_of):
                    row=c.execute("""SELECT data FROM investment_versions WHERE object_id=?
                        AND (data::jsonb->>'updated_at')::timestamptz<=?::timestamptz ORDER BY version DESC LIMIT 1""",(fill['id'],as_of)).fetchone()
                    fills[index]=json.loads(row[0])
        events=[json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_cash_events e
            JOIN investment_objects o ON o.id=e.id WHERE e.account_id=?'''+event_filter+' ORDER BY e.occurred_at,e.id',
            (account_id,as_of,as_of) if as_of else (account_id,))]
        from .reconciliation import apply_notices
        return apply_notices(c,account_id,reconcile(account['opening_cash'],events,fills,opening_positions=account['opening_positions'],marks=marks),as_of)

    def balance(self,account_id,marks=None):
        with db.connect() as c:
            self.lock(c)
            return self._balance(c,account_id,marks or {})

    def transition(self,kind,object_id,version,state,key,reason=''):
        from .planning import transition
        return transition(self,kind,object_id,version,state,key,reason)

    def campaigns(self,account_id):
        with db.connect() as c:
            self.lock(c)
            return self._campaigns(c,account_id)

    def _campaigns(self,c,account_id):
        from .campaigns import project
        account=self._get(c,'accounts',account_id)
        fills=[json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_fills f
            JOIN investment_objects o ON o.id=f.id WHERE f.account_id=? ORDER BY f.executed_at,f.sequence''',(account_id,))]
        from .reconciliation import notices
        affected={n['instrument_id'] for n in notices(c,account_id)}
        cycles=project(account,fills)
        for cycle in cycles:
            if cycle['instrument_id'] in affected:
                cycle.update(net_realized=None,realized_r=None,cost=None,reconciliation_required=True)
        return cycles

    def export(self):
        with db.connect() as c:
            self.lock(c)
            count=c.execute('SELECT count(*) FROM investment_versions').fetchone()[0]
            if count>10000:
                fail('export_too_large','记录较多，请使用管理员完整备份。',422)
            objects=[json.loads(r[0]) for r in c.execute('SELECT data FROM investment_objects ORDER BY created_at,id')]
            versions=[json.loads(r[0]) for r in c.execute('SELECT data FROM investment_versions ORDER BY object_id,version')]
            jobs=[]
            if c.execute("SELECT to_regclass('investment_analysis_jobs')").fetchone()[0]:
                if c.execute('SELECT count(*) FROM investment_analysis_jobs').fetchone()[0]>1000:
                    fail('export_too_large','分析记录较多，请使用管理员完整备份。',422)
                jobs=[{k:v for k,v in json.loads(r[0]).items() if k not in ('worker','fingerprint')}
                      for r in c.execute('SELECT data FROM investment_analysis_jobs ORDER BY id')]
            return {'format':'grow-investments-v1','exported_at':now(),
                'scope':'仅本账号投资对象与历史版本；不含登录、AI密钥、全站数据或外部行情授权。',
                'objects':objects,'versions':versions,'analysis_jobs':jobs}
