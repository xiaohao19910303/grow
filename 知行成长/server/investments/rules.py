"""Versioned public reference facts, not a live security master or order approval."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo
from copilot.core import digest, encoded, now
from .accounting import number
from .contracts import decimal_input

TZ=ZoneInfo('Asia/Shanghai')
RULEBOOK_ID='cn-auction-20261028-v1'
REVIEWED_ON='2026-10-28'
REVIEW_UNTIL='2026-11-27'  # Maintenance deadline, not an exchange-specified expiry.
EFFECTIVE_FROM='2026-07-06'
SOURCES={
    'SSE':{'rules':'https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml',
        'calendar':'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'},
    'SZSE':{'rules':'https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf',
        'calendar':'https://www.szse.cn/disclosure/notice/general/t20251222_618087.html'}}
HOLIDAYS=(('2026-01-01','2026-01-03'),('2026-02-15','2026-02-23'),('2026-04-04','2026-04-06'),
    ('2026-05-01','2026-05-05'),('2026-06-19','2026-06-21'),('2026-09-25','2026-09-27'),('2026-10-01','2026-10-07'))


def _day(stamp):
    return datetime.fromisoformat(stamp).astimezone(TZ).date().isoformat()


def calendar(market,start,end,as_of):
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if last<first or (last-first).days>369:raise ValueError('日历范围须为顺序连续且不超过370日。')
    result={'market':market,'start':start,'end':end,'sessions':{},'status':'coverage_unknown',
        'rulebook_id':RULEBOOK_ID,'source_url':SOURCES.get(market,{}).get('calendar'),
        'reviewed_on':REVIEWED_ON,'review_until':REVIEW_UNTIL,'realtime':False}
    if market not in SOURCES or start<'2026-01-01' or end>'2026-12-31' or _day(as_of)<'2025-12-22':return result
    if _day(as_of)>REVIEW_UNTIL:result['status']='review_expired';return result
    result['status']='available'
    for offset in range((last-first).days+1):
        day=first+timedelta(days=offset);key=day.isoformat()
        result['sessions'][key]=day.weekday()<5 and not any(a<=key<=b for a,b in HOLIDAYS)
    result['snapshot_hash']=digest(encoded(result))
    return result


def rule_context(instrument,on,as_of):
    date.fromisoformat(on)
    market,code,kind=(instrument[k] for k in ('market','code','kind'))
    profile=None
    if kind=='stock' and market=='SSE':
        if code.startswith(('600','601','603','605')):profile='sse_main'
        elif code.startswith('688'):profile='star'
    elif kind=='stock' and market=='SZSE':
        if code.startswith(('000','001','002','003')):profile='szse_main'
        elif code.startswith(('300','301')):profile='chinext'
    elif kind=='etf' and ((market=='SSE' and code.startswith('5')) or (market=='SZSE' and code.startswith('15'))):profile='etf_unclassified'
    if len(code)!=6 or not code.isdigit():profile=None
    status='available'
    if not profile:status='unsupported_identity'
    elif on<EFFECTIVE_FROM:status='historical_unknown'
    elif _day(as_of)>REVIEW_UNTIL or on>REVIEW_UNTIL:status='review_expired'
    elif _day(as_of)<'2026-04-24':status='not_published'
    rules={}
    unknown=['trading_status','price_limits','broker_permissions','current_sellable_quantity','identity_independently_verified']
    if status=='available':
        rules={'price_tick':'0.001' if kind=='etf' else '0.01','minimum_quantity':'200' if profile=='star' else '100',
            'quantity_step':'1' if profile=='star' else '100',
            'maximum_quantity':'100000' if profile=='star' else '300000' if profile=='chinext' else '1000000',
            'sell_delay_sessions':None if kind=='etf' else 1}
        if kind=='etf':unknown.extend(['etf_classification','sell_delay_sessions'])
    result={'instrument_id':instrument['id'],'market':market,'code':code,'kind':kind,'profile':profile,
        'status':status,'rules':rules,'unknown_fields':unknown,'executable':False,'realtime':False,
        'rulebook_id':RULEBOOK_ID,'effective_from':EFFECTIVE_FROM,'reviewed_on':REVIEWED_ON,'review_until':REVIEW_UNTIL,
        'implementation':'implemented_reference_subset' if status=='available' else 'unknown',
        'order_type':'auction_limit_buy','source_url':SOURCES.get(market,{}).get('rules'),
        'locator':'3.1.4–3.1.5、3.3.8–3.3.11；科创板6.7；不覆盖市价/盘后/大宗申报',
        'limitations':['代码前缀仅选择候选规则，未联网核验上市身份或最新特别规定；不确认可成交。',
            '复核截至为应用维护期限，非交易所失效日期；过期关闭自动填入。',
            'ETF回转机制不从代码或通称推定，须另核对具体基金文件。']}
    result['snapshot_hash']=digest(encoded(result))
    return result


def compare_check(instrument,check,on,as_of):
    rules=rule_context(instrument,on,as_of);mismatches=[]
    if rules['status']=='available':
        for field in ('price_tick','minimum_quantity','quantity_step','sell_delay_sessions'):
            expected=rules['rules'].get(field)
            if expected is not None and Decimal(str(check[field]))!=Decimal(str(expected)):
                mismatches.append({'field':field,'recorded':check[field],'expected':expected})
    days=sorted(check['sessions'])
    cal=calendar(instrument['market'],days[0],days[-1],as_of)
    if cal['status']=='available':
        for day,value in check['sessions'].items():
            if value!=cal['sessions'][day]:mismatches.append({'field':'sessions.'+day,'recorded':value,'expected':cal['sessions'][day]})
    return {'status':'mismatch' if mismatches else 'matched_reference_subset' if rules['status']=='available' else 'unavailable',
        'mismatches':mismatches[:20],'mismatch_count':len(mismatches),'rules':rules,'calendar':cal,
        'executable':False,'trading_status_source':'user_declared'}


def normalize_units(volume,amount,volume_unit,amount_unit):
    if volume_unit not in ('shares','lots100') or amount_unit not in ('cny','thousand_cny'):
        raise ValueError('来源单位未知，不允许猜测或合并。')
    values=[None if v is None else decimal_input(v) for v in (volume,amount)]
    if any(v is not None and (v<0 or v>=Decimal('1e20') or v.as_tuple().exponent < -10) for v in values):
        raise ValueError('成交量额超过有效范围或精度。')
    with localcontext() as ctx:
        ctx.prec=60
        return {'volume_shares':number(values[0]*(100 if volume_unit=='lots100' else 1)) if values[0] is not None else None,
            'turnover_cny':number(values[1]*(1000 if amount_unit=='thousand_cny' else 1)) if values[1] is not None else None,
            'source_volume':number(values[0]),'source_amount':number(values[1]),'source_units':{'volume':volume_unit,'amount':amount_unit}}


def freshness(market,latest_day,as_of):
    stamp=datetime.fromisoformat(as_of).astimezone(TZ);day=stamp.date()
    start=max(date(day.year,1,1),day-timedelta(days=31))
    cal=calendar(market,start.isoformat(),day.isoformat(),as_of)
    complete=[d for d,opened in cal['sessions'].items() if opened and (d<day.isoformat() or stamp.time()>=time(15,30))]
    expected=max(complete) if complete else None
    status='missing' if latest_day is None else 'coverage_unknown'
    if latest_day is not None:
        date.fromisoformat(latest_day)
        if expected is not None:
            status='incomplete_or_future' if latest_day>expected else 'closed_session_record' if cal['sessions'].get(latest_day) is False else 'latest_completed_session' if latest_day==expected else 'stale'
    return {'status':status,'latest_day':latest_day,'expected_session':expected,'as_of':as_of,'realtime':False,
        'calendar_status':cal['status'],'calendar_source':cal['source_url'],
        'trading_status':'unknown','reason':'缺记录不能判断停牌；盘后日线不代表盘中行情。',
        'completion_gate':'15:30 Asia/Shanghai；保守等待盘后交易窗口结束，不承诺供应商此时已入库。'}


def data_status(store,instrument_id):
    import db
    with db.connect() as c:
        instrument=store._get(c,'instruments',instrument_id)
        row=c.execute("""SELECT data::jsonb->'bars'->-1->>'date',data::jsonb->>'provider',
            data::jsonb->>'retrieved_at' FROM investment_objects WHERE kind='market-snapshots'
            AND data::jsonb->>'instrument_id'=? ORDER BY created_at DESC,id DESC LIMIT 1""",(instrument_id,)).fetchone()
        result=freshness(instrument['market'],row[0] if row else None,now())
        return {**result,'instrument_id':instrument_id,'source_provider':row[1] if row else None,
            'retrieved_at':row[2] if row else None,'source_independently_verified':False}
