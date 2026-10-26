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
        except ValidationError:
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
            rows = c.execute('SELECT data FROM investment_objects WHERE '+where+
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
        account = self._get(c,'accounts',data['account_id']) if 'account_id' in data else None
        if 'instrument_id' in data:
            self._get(c,'instruments',data['instrument_id'])
        for opening in data.get('opening_positions',[]):
            self._get(c,'instruments',opening['instrument_id'])
        if len({p['instrument_id'] for p in data.get('opening_positions',[])}) != len(data.get('opening_positions',[])):
            fail('validation_error','期初同一证券请合并为一条持仓。',422)
        if data.get('strategy_id'):
            self._get(c,'strategies',data['strategy_id'])
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

    def create(self,kind,payload,key):
        data = self.validate(kind,payload)
        fingerprint = digest(encoded({'kind':kind,'data':data}))
        with db.connect() as c:
            self.lock(c)
            old = self.replay(c,key,fingerprint)
            if old is not None:
                return old
            self.references(c,kind,data)
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
            if kind in ('policies','strategies','trade-plans'):
                record['state']='draft'
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
            if kind not in ('policies','strategies','trade-plans','reviews'):
                fail('immutable_fact','此事实需通过专用核对流程更正，不能覆盖。')
            data=self.validate(kind,payload)
            self.references(c,kind,data)
            if old.get('account_id') != data.get('account_id'):
                fail('validation_error','已有记录不能移到另一个账户。',422)
            record={**data,'id':object_id,'version':version+1,'created_at':old['created_at'],'updated_at':now()}
            if 'state' in old:
                record['state']='draft'
            self.save(c,kind,record)
            self.remember(c,key,fingerprint,record)
            return record

    def _balance(self,c,account_id,marks):
        account=self._get(c,'accounts',account_id)
        fills=[json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_fills f
            JOIN investment_objects o ON o.id=f.id WHERE f.account_id=? ORDER BY f.executed_at,f.sequence''',(account_id,))]
        events=[json.loads(r[0]) for r in c.execute('''SELECT o.data FROM investment_cash_events e
            JOIN investment_objects o ON o.id=e.id WHERE e.account_id=? ORDER BY e.occurred_at,e.id''',(account_id,))]
        return reconcile(account['opening_cash'],events,fills,opening_positions=account['opening_positions'],marks=marks)

    def balance(self,account_id,marks=None):
        with db.connect() as c:
            self.lock(c)
            return self._balance(c,account_id,marks or {})
