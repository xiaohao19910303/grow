"""Private daily-history CSV import: explicit units and provenance, no paid dependency."""
import csv
import io
import uuid
from datetime import date

import db
from copilot.core import Problem, digest, encoded, fail, now
from .accounting import number
from .providers import decimal_value, indicators


def import_history(store,instrument_id,text,volume_unit,amount_unit,source_label,use_confirmed,key,account_id=None):
    if not use_confirmed or volume_unit not in ('shares','lots') or amount_unit not in ('cny','thousand_cny'):
        fail('invalid_import','请确认资料用途、未复权口径和量额单位。',422)
    if not isinstance(text,str) or len(text.encode('utf-8'))>250000 or not 1<=len(source_label)<=100:
        fail('invalid_import','请填写来源，使用250KB以内、最多200行的日线CSV。',422)
    fingerprint=digest(encoded({'history_import':instrument_id,'text':text,'volume_unit':volume_unit,
        'amount_unit':amount_unit,'source_label':source_label,'account_id':account_id}))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:
            return replay
        instrument=store._get(c,'instruments',instrument_id)
        if account_id:
            store._get(c,'accounts',account_id)
        bars=[];seen=set()
        try:
            aliases={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'}
            reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
            required={'date','open','high','low','close','volume','amount'}
            columns=[aliases.get(k,k) for k in reader.fieldnames or []]
            if len(columns)!=len(set(columns)) or not required.issubset(columns):
                raise ValueError()
            for index,raw in enumerate(reader):
                if index>=200:
                    raise ValueError()
                row={aliases.get(k,k):v for k,v in raw.items()}
                day=date.fromisoformat(row['date']).isoformat()
                if day in seen:
                    raise ValueError()
                seen.add(day)
                values={k:decimal_value(row[k]) for k in ('open','high','low','close','volume','amount')}
                if values['low']<=0 or not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
                    raise ValueError()
                bars.append({'date':day,**{k:number(values[k]) for k in ('open','high','low','close')},
                    'volume_shares':number(values['volume']*(100 if volume_unit=='lots' else 1)),
                    'turnover_cny':number(values['amount']*(1000 if amount_unit=='thousand_cny' else 1)),
                    'source_volume':number(values['volume']),'source_amount':number(values['amount'])})
            if not bars:
                raise ValueError()
        except (Problem,ValueError,KeyError,TypeError,csv.Error):
            fail('invalid_history_csv','请核对列名、有效日期、非负量额、OHLC关系和重复日期。',422)
        bars.sort(key=lambda b:b['date'])
        stamp=now()
        snapshot={'id':'market-'+uuid.uuid4().hex,'version':1,'created_at':stamp,'updated_at':stamp,
            'instrument_id':instrument_id,'provider':'user_import','declared_source':source_label,
            'retrieved_at':stamp,'available_at':stamp,'freshness':'manual_unverified','coverage':'imported_daily',
            'realtime':False,'price_basis':'unadjusted_user_declared','bars':bars,'calendar':{},
            'source_units':{'volume':volume_unit,'amount':amount_unit},'indicators':indicators(bars),
            'limitations':['来源与未复权口径由本人声明，未独立核验。','缺少交易日历和实时状态，不能据此确认当前可成交。']}
        content=encoded({k:v for k,v in {**snapshot,'bars':bars[-20:],'omitted_bar_count':max(0,len(bars)-20)}.items()
                         if k not in ('id','version','created_at','updated_at','calendar')})
        if len(content)>12000:
            fail('import_summary_too_large','摘要超过限制，请缩小日期范围。',422)
        evidence=store.validate('research',{'instrument_id':instrument_id,'account_id':account_id,
            'title':instrument['name']+' · 本人导入日线 '+bars[-1]['date'],'content':content,
            'available_at':stamp,'locator':'CSV导入；来源声明 '+source_label,
            'contrary_evidence':'需核对源单位、复权口径、公司行动、缺失交易日和当前状态。'})
        record=store.create_in(c,'research',evidence,'history-evidence-'+digest(key+fingerprint))
        store.save(c,'market-snapshots',snapshot,fresh=True)
        result={**snapshot,'snapshot_id':snapshot['id'],'evidence_id':record['id']}
        store.remember(c,key,fingerprint,result)
        return result
