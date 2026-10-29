"""Explicit Eastmoney daily snapshots, independent of CSV and Tushare."""
import json
import re
import subprocess
import sys
import threading
import uuid
from datetime import date,datetime,time
from pathlib import Path

import db
from copilot.core import digest,encoded,fail,now
from .accounting import number
from .providers import decimal_value,indicators,TZ
from .market_evidence import daily_excerpt
from .rules import calendar,freshness,normalize_units,rule_context

_request_slot=threading.BoundedSemaphore(1)
DOCS={'stock':'https://akshare.akfamily.xyz/data/stock/stock_quote.html',
      'etf':'https://akshare.akfamily.xyz/data/fund/fund_public.html'}
ENDPOINTS={'stock':'stock_zh_a_hist','etf':'fund_etf_hist_em'}


def load_rows(kind,code,start,end):
    # AKShare部分接口无超时参数；独立进程在45秒后终止，避免请求线程持续挂起。
    if not _request_slot.acquire(blocking=False):
        fail('provider_busy','已有东方财富日线取数进行中，请稍后手动重试。',409)
    try:
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('akshare_worker.py'))],
            input=encoded({'kind':kind,'code':code,'start':start,'end':end}),
            capture_output=True,text=True,timeout=45,check=False)
        if result.returncode or len(result.stdout)>200000:
            fail('provider_unavailable','东方财富日线未完成；未切换来源，请稍后手动重试或使用CSV。',502)
        packet=json.loads(result.stdout)
        if not isinstance(packet,dict):raise ValueError('Unexpected worker response')
        if packet.get('error')=='dependency_missing':
            fail('provider_dependency_missing','服务端尚未安装锁定的AKShare依赖，请按项目依赖清单安装。',503)
        if packet.get('error'):
            fail('provider_unavailable','东方财富日线暂不可用或返回格式已变化；未保存行情、未自动换源。',502)
        return packet
    except subprocess.TimeoutExpired:
        fail('provider_timeout','东方财富取数超过45秒，已停止；未保存行情、未自动重试或换源。',504)
    except (OSError,ValueError,TypeError):
        fail('provider_unavailable','东方财富日线响应无法读取；请稍后手动重试或使用CSV。',502)
    finally:
        _request_slot.release()


class AKShareDailyProvider:
    """东方财富盘后行情：校验来源、日历和量额，事务保存行情及AI研究证据。"""
    def __init__(self,store,loader=None):
        self.store=store;self.loader=loader or load_rows

    def fetch(self,instrument_id,start_date,end_date,use_confirmed,key,account_id=None):
        if not use_confirmed:
            fail('use_confirmation_required','请先核对并确认公开数据的使用范围。',422)
        try:
            start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
            if start>end or (end-start).days>90:raise ValueError()
        except (ValueError,TypeError):
            fail('invalid_range','请选择最多90个自然日的日期范围。',422)
        fingerprint=digest(encoded({'provider':'akshare-eastmoney-daily-v1','instrument_id':instrument_id,
            'start_date':start_date,'end_date':end_date,'account_id':account_id}))
        with db.connect() as c:
            self.store.lock(c)
            old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            instrument=self.store._get(c,'instruments',instrument_id)
            if account_id:self.store._get(c,'accounts',account_id)
        kind,market,code=(instrument[k] for k in ('kind','market','code'))
        stamp=now();asof=datetime.fromisoformat(stamp).astimezone(TZ)
        if kind not in ENDPOINTS or market not in ('SSE','SZSE'):
            fail('provider_unsupported','东方财富首版仅接入沪深股票及场内ETF盘后日线。',422)
        if not re.fullmatch(r'\d{6}',code) or not rule_context(instrument,end_date,stamp)['profile']:
            fail('invalid_instrument','请核对六位证券代码、所属市场及股票/ETF品种。',422)
        if end>asof.date() or (end==asof.date() and asof.time()<time(15,30)):
            fail('incomplete_session','请使用已完成的盘后日期；15:30前不读取当日日线。',422)
        reference=calendar(market,start_date,end_date,stamp)
        if reference['status']!='available':
            fail('public_calendar_unavailable','公开日历未覆盖本次日期或已过复核期，请核对范围；不会自动换源。',422)
        packet=self.loader(kind,code,start_date,end_date)
        if not isinstance(packet,dict) or not isinstance(packet.get('rows'),list) or len(packet['rows'])>200:
            fail('provider_invalid','东方财富返回的数据范围或格式无效。',502)
        if not packet['rows']:
            fail('provider_empty','东方财富未返回该标的在所选期间的日线；不推断停牌、不保存零值或覆盖已有行情。',422)
        bars=[];seen=set()
        for row in packet['rows']:
            try:
                day=date.fromisoformat(str(row['日期'])).isoformat()
                if not start_date<=day<=end_date or day in seen or not reference['sessions'].get(day):raise ValueError()
                values={k:decimal_value(row[label]) for k,label in
                    [('open','开盘'),('high','最高'),('low','最低'),('close','收盘'),('volume','成交量'),('amount','成交额')]}
                if values['low']<=0 or not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
                    raise ValueError()
            except (KeyError,TypeError,ValueError):
                fail('provider_invalid','东方财富返回的日期、量额或OHLC关系无效，未保存行情。',502)
            seen.add(day)
            bars.append({'date':day,**{k:number(values[k]) for k in ('open','high','low','close')},
                **{k:v for k,v in normalize_units(values['volume'],values['amount'],'lots100','cny').items() if k!='source_units'}})
        bars.sort(key=lambda b:b['date']);retrieved=now()
        # 保留原始单位和获取时点；与Tushare千元口径区分，旧来源快照不改写。
        result={'instrument_id':instrument_id,'provider':'akshare_eastmoney','upstream':'eastmoney',
            'endpoint':ENDPOINTS[kind],'library_version':packet.get('library_version'),
            'coverage':'daily_only','realtime':False,'price_basis':'unadjusted',
            'retrieved_at':retrieved,'available_at':retrieved,'requested_start':start_date,'requested_end':end_date,
            'latest_session':bars[-1]['date'],'bars':bars,'freshness':freshness(market,bars[-1]['date'],retrieved)['status'],
            'data_status':freshness(market,bars[-1]['date'],retrieved),'indicators':indicators(bars),
            'calendar_source':{k:v for k,v in reference.items() if k!='sessions'},
            'source_units':{'volume':'lot_100_shares','amount':'CNY'},
            'limitations':['未复权日线；成交量由手转股/份，成交额原单位为元。',
                '本次获取的资料不能倒灌为历史事前证据；缺记录不推断停牌，未核验实时状态。',
                '公开接口可能限流、延迟或变更；用途和来源许可由本人核对，未自动换源或合并历史。']}
        with db.connect() as c:
            self.store.lock(c)
            old=self.store.replay(c,key,fingerprint)
            if old is not None:return old
            content=encoded({**{k:v for k,v in result.items() if k not in ('instrument_id','bars','calendar_source')},
                **daily_excerpt(bars)})
            if len(content)>12000:fail('evidence_too_large','行情摘要超出资料限制，请缩小日期范围。',422)
            evidence=self.store.validate('research',{'account_id':account_id,'instrument_id':instrument_id,
                'title':instrument['name']+' · 东方财富盘后行情 '+bars[-1]['date'],'content':content,
                'source_url':DOCS[kind],'available_at':retrieved,'locator':ENDPOINTS[kind]+' '+market+' '+code,
                'contrary_evidence':'未复权资料；公司行动、停牌与当前交易规则仍需核对。'})
            record=self.store.create_in(c,'research',evidence,'akshare-evidence-'+digest(key+fingerprint))
            snapshot={'id':'market-'+uuid.uuid4().hex,'version':1,'created_at':retrieved,'updated_at':retrieved,**result}
            self.store.save(c,'market-snapshots',snapshot,fresh=True)
            result={**result,'snapshot_id':snapshot['id'],'evidence_id':record['id']}
            self.store.remember(c,key,fingerprint,result)
            return result
