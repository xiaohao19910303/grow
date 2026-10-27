"""Bounded Tushare daily adapter. No HTTP downgrade, stored tokens or realtime claims."""
import json
import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import db
import httpx
from copilot.core import digest, encoded, fail, now
from .accounting import number

D=Decimal
TZ=ZoneInfo('Asia/Shanghai')
HOST='https://api.tushare.pro'


def decimal_value(value):
    try:
        result=D(str(value))
        if not result.is_finite() or result<0 or result>=D('1e20') or result.as_tuple().exponent < -10:
            raise ValueError()
        return result
    except Exception:
        fail('provider_invalid','数据商返回了无效数值，请核对原始记录。',502)


def rows(data):
    if not isinstance(data,dict) or not isinstance(data.get('fields'),list) or not isinstance(data.get('items'),list):
        fail('provider_invalid','数据商返回格式不符合合同。',502)
    fields=data['fields'];items=data['items']
    if len(items)>200 or len(fields)!=len(set(fields)) or len(fields)>30 or not all(isinstance(f,str) for f in fields):
        fail('provider_invalid','数据商返回的范围超过限制。',502)
    if any(not isinstance(item,list) or len(item)!=len(fields) for item in items):
        fail('provider_invalid','数据商返回了不完整数据行。',502)
    return [dict(zip(fields,item)) for item in items]


def indicators(bars):
    with localcontext() as ctx:
        ctx.prec=60
        return _indicators(bars)


def _indicators(bars):
    ordered=sorted(bars,key=lambda b:b['date'])
    output={'price_basis':'unadjusted','ma5':None,'ma20':None,'volume_ratio_5':None,'atr14':None,
        'record_return_std20':None,'return_sample_count':max(0,min(20,len(ordered)-1)),
        'limitations':['未复权；除权与公司行动可能影响指标，不能据此推定可执行交易。']}
    for window in (5,20):
        if len(ordered)>=window:
            output['ma'+str(window)]=number(sum((D(b['close']) for b in ordered[-window:]),D('0'))/window)
    if len(ordered)>=6:
        previous=sum((D(b['volume_shares']) for b in ordered[-6:-1]),D('0'))/5
        if previous:
            output['volume_ratio_5']=number(D(ordered[-1]['volume_shares'])/previous)
    if len(ordered)>=15 and all('high' in b and 'low' in b for b in ordered[-14:]):
        true_ranges=[max(D(b['high'])-D(b['low']),abs(D(b['high'])-D(p['close'])),abs(D(b['low'])-D(p['close'])))
            for p,b in zip(ordered[-15:-1],ordered[-14:])]
        output['atr14']=number(sum(true_ranges,D('0'))/14)
    if len(ordered)>=21 and all(D(b['close'])>0 for b in ordered[-21:]):
        returns=[D(b['close'])/D(p['close'])-1 for p,b in zip(ordered[-21:-1],ordered[-20:])]
        mean=sum(returns,D('0'))/20
        output['record_return_std20']=number((sum(((r-mean)**2 for r in returns),D('0'))/19).sqrt())
    output['limitations'].append('ATR为最近14条真实区间的简单均值；波动为20次相邻有效记录收益样本标准差，不年化，不保证相邻自然日开市。')
    return output


class DailyProvider:
    def __init__(self,store,transport=None):
        self.store=store;self.transport=transport

    async def request(self,api_name,params,fields,token):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25,connect=8),follow_redirects=False,transport=self.transport) as client:
                async with client.stream('POST',HOST,json={'api_name':api_name,'token':token,'params':params,'fields':fields}) as response:
                    if response.status_code!=200:
                        fail('provider_http','行情服务连接失败；不会降级为明文连接或自动重试。',502)
                    raw=bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>2000000:
                            fail('provider_too_large','数据商响应过大，请缩小日期范围。',502)
            packet=json.loads(raw,parse_float=D)
            if not isinstance(packet,dict) or packet.get('code')!=0:
                fail('provider_permission','数据商未允许本次请求，请核对接口权限、额度与凭证。',422)
            return rows(packet.get('data'))
        except httpx.HTTPError:
            fail('provider_unavailable','行情服务连接未完成；未保存凭证，也不会自动重试。',502)
        except (ValueError,TypeError):
            fail('provider_invalid','数据商返回格式无法读取。',502)

    async def fetch(self,instrument_id,start_date,end_date,token,licensed_use_confirmed,key,account_id=None):
        try:
            start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
            if start>end or (end-start).days>90:
                raise ValueError()
        except (ValueError,TypeError):
            fail('invalid_range','请选择最多90个自然日的日期范围。',422)
        if not licensed_use_confirmed:
            fail('use_confirmation_required','请先核对并确认个人使用权限和用途。',422)
        if not isinstance(token,str) or not 8<=len(token)<=4096 or re.search(r'[\x00-\x20]',token):
            fail('invalid_provider_config','请填写有效的本人数据商凭证。',422)
        fingerprint=digest(encoded({'provider':'tushare-daily-v1','instrument_id':instrument_id,
            'start_date':start_date,'end_date':end_date,'account_id':account_id}))
        with db.connect() as c:
            self.store.lock(c)
            old=self.store.replay(c,key,fingerprint)
            if old is not None:
                return old
            instrument=self.store._get(c,'instruments',instrument_id)
            if account_id:
                self.store._get(c,'accounts',account_id)
        if instrument['kind'] not in ('stock','etf') or instrument['market'] not in ('SSE','SZSE','BSE'):
            fail('provider_unsupported','此适配器只读取A股/场内ETF盘后行情；场外净值尚待独立核验。',422)
        if instrument['market']=='BSE':
            fail('provider_unsupported','北交所日历尚未独立核验，不能用沪深日历替代。请使用手工核对资料。',422)
        suffix={'SSE':'.SH','SZSE':'.SZ','BSE':'.BJ'}[instrument['market']]
        code=instrument['code']
        plain=code[:-3] if code.endswith(suffix) else code
        if not re.fullmatch(r'\d{6}',plain):
            fail('invalid_instrument','请核对证券代码与市场。',422)
        ts_code=plain+suffix
        compact=lambda d:d.replace('-','')
        exchange=instrument['market']
        calendar=await self.request('trade_cal',{'exchange':exchange,
            'start_date':compact(start_date),'end_date':compact(end_date)},'exchange,cal_date,is_open,pretrade_date',token)
        calendar_by_date={}
        for item in calendar:
            try:
                day=datetime.strptime(str(item['cal_date']),'%Y%m%d').date().isoformat()
                if item.get('exchange')!=exchange or not start_date<=day<=end_date or str(item['is_open']) not in ('0','1') or day in calendar_by_date:
                    raise ValueError()
                calendar_by_date[day]=str(item['is_open'])=='1'
            except (ValueError,KeyError):
                fail('provider_calendar','交易日历格式或覆盖无效。',502)
        if any((start+timedelta(days=n)).isoformat() not in calendar_by_date for n in range((end-start).days+1)):
            fail('provider_calendar','交易日历范围不完整，不能推断休市和数据新鲜度。',502)
        endpoint='fund_daily' if instrument['kind']=='etf' else 'daily'
        raw=await self.request(endpoint,{'ts_code':ts_code,'start_date':compact(start_date),'end_date':compact(end_date)},
            'ts_code,trade_date,open,high,low,close,vol,amount',token)
        bars=[];seen=set();retrieved=now();asof=datetime.fromisoformat(retrieved).astimezone(TZ)
        for item in raw:
            try:
                day=datetime.strptime(str(item['trade_date']),'%Y%m%d').date().isoformat()
                if item['ts_code']!=ts_code or not start_date<=day<=end_date or day in seen or not calendar_by_date.get(day) or day>asof.date().isoformat() or (day==asof.date().isoformat() and asof.time()<time(15)):
                    raise ValueError()
                values={k:decimal_value(item[k]) for k in ('open','high','low','close','vol','amount')}
                if not (values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']) or values['low']<=0:
                    raise ValueError()
            except (ValueError,KeyError):
                fail('provider_invalid','行情证券、日期或OHLC数据不一致。',502)
            seen.add(day)
            bars.append({'date':day,**{k:number(values[k]) for k in ('open','high','low','close')},
                'volume_shares':number(values['vol']*100),'turnover_cny':number(values['amount']*1000),
                'source_volume':number(values['vol']),'source_amount':number(values['amount'])})
        bars.sort(key=lambda b:b['date'])
        expected=[day for day,is_open in calendar_by_date.items() if is_open and day<=asof.date().isoformat()
            and (day<asof.date().isoformat() or asof.time()>=time(15))]
        expected=max(expected) if expected else None
        latest=bars[-1]['date'] if bars else None
        freshness=('previous_close' if asof.time()<time(15) else 'daily_asof') if latest and latest==expected and end>=asof.date() else 'historical_or_incomplete'
        result={'instrument_id':instrument_id,'provider':'tushare','endpoint':endpoint,'coverage':'daily_only',
            'realtime':False,'retrieved_at':retrieved,'available_at':retrieved,
            'requested_start':start_date,'requested_end':end_date,'latest_session':latest,
            'expected_session_within_requested_range':expected,'freshness':freshness,
            'bars':bars,'calendar':calendar_by_date,'indicators':indicators(bars),
            'source_units':{'volume':'lot_100_shares','amount':'thousand_CNY'},
            'permission_note':'仅本次接口访问成功；用途由本人确认，未验证实时权限或再分发许可。',
            'limitations':['历史资料本次才抓取；无法证明当时已入库，不能倒灌为历史事前证据。',
                '无返回不等于价格为零或已停牌；公司行动、公告、财务与交易规则需另行核对。']}
        with db.connect() as c:
            self.store.lock(c)
            old=self.store.replay(c,key,fingerprint)
            if old is not None:
                return old
            content=encoded({**{k:v for k,v in result.items() if k not in ('instrument_id','calendar','bars')},
                'bars':bars[-20:],'omitted_bar_count':max(0,len(bars)-20)})
            if len(content)>12000:
                fail('evidence_too_large','行情摘要超出资料大小限制，请缩小范围。',422)
            evidence=self.store.validate('research',{'account_id':account_id,'instrument_id':instrument_id,
                'title':instrument['name']+' · 盘后行情 '+(latest or '未返回记录'),
                'content':content, 'source_url':'https://tushare.pro/document/2?doc_id='+('127' if endpoint=='fund_daily' else '27'),
                'available_at':retrieved,'locator':endpoint+' '+ts_code,'contrary_evidence':'未复权资料；缺少公司行动、实时与成交约束核验。'})
            record=self.store.create_in(c,'research',evidence,'daily-evidence-'+digest(key+fingerprint))
            stamp=now();snapshot={'id':'market-'+uuid.uuid4().hex,'version':1,'created_at':stamp,'updated_at':stamp,**result}
            self.store.save(c,'market-snapshots',snapshot,fresh=True)
            result={**result,'snapshot_id':snapshot['id'],'evidence_id':record['id']}
            self.store.remember(c,key,fingerprint,result)
            return result
