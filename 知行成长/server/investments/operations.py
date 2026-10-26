"""Explicit previews, all-or-nothing imports, audited corrections and fund receipts."""
import csv
import io
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import db
from pydantic import ValidationError
from copilot.core import Problem, digest, encoded, fail, now
from .accounting import number
from .contracts import FundConfirmation, RESOURCE_MODELS


def preview_csv(store,account_id,text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>250000:
        fail('csv_too_large','请使用250KB以内、最多200行的CSV。',422)
    rows,errors=[],[]
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        instruments=[json.loads(r[0]) for r in c.execute("SELECT data FROM investment_objects WHERE kind='instruments'")]
        known={(i['market'],i['code']):i['id'] for i in instruments}
    try:
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        required={'code','market','side','price','quantity','executed_at','external_id'}
        if not required.issubset(reader.fieldnames or []):
            fail('invalid_csv','缺少CSV列：code,market,side,price,quantity,executed_at,external_id。',422)
        for line,row in enumerate(reader,2):
            if line>201:
                fail('csv_too_large','每批最多200条成交。',422)
            try:
                instrument=known.get((row.get('market'),row.get('code')))
                if not instrument or not (row.get('external_id') or '').strip():
                    raise ValueError('请先添加对应市场/代码的标的，并填写可核对的外部成交编号。')
                value=store.validate('fills',{'account_id':account_id,'instrument_id':instrument,
                    'side':row['side'],'price':row['price'],'quantity':row['quantity'],
                    'fee':row.get('fee') or None,'tax':row.get('tax') or None,
                    'executed_at':row['executed_at'],'external_id':row['external_id'],'source':'csv','note':row.get('note') or ''})
                rows.append({'line':line,'data':value})
            except (Problem, ValueError) as exc:
                errors.append({'line':line,'message':getattr(exc,'message',str(exc))})
    except csv.Error:
        fail('invalid_csv','CSV格式无效。',422)
    return {'rows':rows,'errors':errors,'token':digest(encoded({'account_id':account_id,'text':text})),
            'scope':'仅实际成交；缺外部编号的记录请先手工核对。'}


def commit_csv(store,account_id,text,token,key):
    preview=preview_csv(store,account_id,text)
    if preview['token']!=token:
        fail('preview_changed','CSV或账户已改变，请重新预览。')
    if preview['errors'] or not preview['rows']:
        fail('invalid_csv','请先修正预览错误，或填写至少一行成交。',422)
    fingerprint=digest(encoded({'csv':token}))
    with db.connect() as c:
        store.lock(c)
        old=store.replay(c,key,fingerprint)
        if old is not None:
            return old
        ids=[]
        for row in preview['rows']:
            data=row['data']
            record=store.create_in(c,'fills',data,'csv-row-'+digest(encoded(data)))
            ids.append(record['id'])
        result={'ids':ids,'count':len(ids),'token':token}
        store.remember(c,key,fingerprint,result)
        return result


def correct_fill(store,object_id,version,changes,reason,key):
    allowed={'price','quantity','fee','tax','note'}
    if not changes or not set(changes).issubset(allowed) or not isinstance(reason,str) or not reason.strip() or len(reason)>2000:
        fail('invalid_correction','请填写核对原因；此流程仅更正价格、数量、费用、税费或备注。',422)
    fingerprint=digest(encoded({'correction':object_id,'version':version,'changes':changes,'reason':reason}))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        old=store._get(c,'fills',object_id)
        if old.get('source')=='fund_confirmation':
            fail('fund_correction_required','基金确认成交关联净值、份额与待到账金额，不能单独更正。请先核对完整确认记录。',422)
        if old['version']!=version:
            fail('version_conflict','成交已更新，请先载入最新版本。')
        data=store.validate('fills',{**{k:old[k] for k in RESOURCE_MODELS['fills'].model_fields if k in old},**changes})
        record={**old,**data,'version':version+1,'updated_at':now(),'correction_reason':reason}
        store.save(c,'fills',record)
        c.execute('UPDATE investment_fills SET price=?,quantity=?,fee=?,tax=? WHERE id=?',
                  (record['price'],record['quantity'],record['fee'],record['tax'],object_id))
        try:
            store._balance(c,old['account_id'],{})
        except ValueError as exc:
            fail('reconciliation_required',str(exc),422)
        store.remember(c,key,fingerprint,record)
        return record


def confirm_fund(store,object_id,version,payload,key):
    try:
        data=FundConfirmation.model_validate(payload).model_dump(mode='json')
    except ValidationError:
        fail('invalid_confirmation','请填写实际确认净值、份额、费用、税费、确认时间与净值日期。',422)
    fingerprint=digest(encoded({'fund_confirmation':object_id,'version':version,'data':data}))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        order=store._get(c,'fund-orders',object_id)
        if order['version']!=version or order['state']!='pending':
            fail('version_conflict','基金申请已变化或已经确认。')
        stamp=datetime.fromisoformat(data['confirmed_at'])
        if stamp<datetime.fromisoformat(order['applied_at']) or data['nav_date']>stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat():
            fail('invalid_confirmation','请核对申请、净值日期与确认时间顺序。',422)
        buy=order['side']=='subscription'
        quantity=Decimal(data['quantity']);gross=Decimal(data['price'])*quantity
        charges=Decimal(data['fee'])+Decimal(data['tax'])
        if (buy and gross+charges>Decimal(order['amount'])) or (not buy and quantity>Decimal(order['quantity'])):
            fail('invalid_confirmation','确认金额或份额超出原申请，请先核对。',422)
        if not buy and gross<charges:
            fail('invalid_confirmation','赎回费用不能大于确认总额。',422)
        fill=store.validate('fills',{'account_id':order['account_id'],'instrument_id':order['instrument_id'],
            'side':'buy' if buy else 'sell','price':data['price'],'quantity':data['quantity'],
            'fee':data['fee'],'tax':data['tax'],'executed_at':data['confirmed_at'],
            'source':'fund_confirmation','external_id':object_id,'note':'基金确认，净值日期 '+data['nav_date']})
        recorded=store.create_in(c,'fills',fill,'fund-fill-'+object_id)
        net=number(gross-charges)
        if not buy and Decimal(net)>0:
            event=store.validate('cash-events',{'account_id':order['account_id'],'kind':'fund_receivable_hold',
                'amount':net,'occurred_at':data['confirmed_at'],'note':'基金赎回待到账 '+object_id})
            store.create_in(c,'cash-events',event,'fund-hold-'+object_id)
        record={**order,'version':version+1,'updated_at':now(),'state':'confirmed' if not buy else 'settled',
                'confirmation':data,'fill_id':recorded['id'],'receivable':net if not buy else '0'}
        store.save(c,'fund-orders',record)
        store.remember(c,key,fingerprint,record)
        return record


def settle_fund(store,object_id,version,received_at,key):
    fingerprint=digest(encoded({'fund_settlement':object_id,'version':version,'received_at':received_at}))
    try:
        stamp=datetime.fromisoformat(received_at)
        if stamp.tzinfo is None:
            raise ValueError()
    except (ValueError,TypeError):
        fail('invalid_settlement','到账时间需要包含时区。',422)
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        order=store._get(c,'fund-orders',object_id)
        if order['version']!=version or order['state']!='confirmed' or order['side']!='redemption':
            fail('version_conflict','申请已变化或当前无待到账赎回。')
        if stamp<datetime.fromisoformat(order['confirmation']['confirmed_at']):
            fail('invalid_settlement','到账不能早于确认时间。',422)
        if Decimal(order['receivable'])>0:
            event=store.validate('cash-events',{'account_id':order['account_id'],'kind':'fund_receivable_release',
                'amount':order['receivable'],'occurred_at':received_at,'note':'核对实际赎回到账 '+object_id})
            store.create_in(c,'cash-events',event,'fund-release-'+object_id)
        record={**order,'version':version+1,'updated_at':now(),'state':'settled','received_at':received_at}
        store.save(c,'fund-orders',record)
        store.remember(c,key,fingerprint,record)
        return record
