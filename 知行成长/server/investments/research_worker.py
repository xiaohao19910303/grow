"""One selected AKShare supplier per bounded process; no automatic source fallback."""
import contextlib
import io
import json
import sys
from datetime import date
from decimal import Decimal,localcontext


def error_packet(error):
    """Only expose a fixed category and exception class, never URLs or credentials."""
    if isinstance(error,ImportError):return {'error':'dependency_missing','error_type':type(error).__name__}
    import requests
    if isinstance(error,requests.exceptions.Timeout):reason='upstream_timeout'
    elif isinstance(error,requests.exceptions.HTTPError):
        reason='upstream_rate_limit' if error.response is not None and error.response.status_code==429 else 'upstream_http'
    elif isinstance(error,requests.exceptions.ConnectionError):reason='upstream_connection'
    elif isinstance(error,(KeyError,ValueError,TypeError,IndexError)):reason='upstream_format'
    else:reason='upstream_unavailable'
    return {'error':reason,'error_type':type(error).__name__}


@contextlib.contextmanager
def single_attempt_pagination():
    # Locked AKShare 1.20.1 retries every Eastmoney page three times. Keep the
    # application's no-retry contract inside this disposable worker only.
    import akshare.utils.func as pagination
    import requests
    original_request=requests.sessions.Session.request
    def checked_request(session,*args,**kwargs):
        response=original_request(session,*args,**kwargs)
        response.raise_for_status()
        return response
    requests.sessions.Session.request=checked_request
    original=pagination.request_with_retry
    def once(url,**kwargs):
        kwargs['max_retries']=1
        return original(url,**kwargs)
    pagination.request_with_retry=once
    try:yield
    finally:
        pagination.request_with_retry=original
        requests.sessions.Session.request=original_request


def tencent_daily(request):
    """AKShare-compatible Tencent protocol, retaining decimal strings before pandas.

    AKShare 1.20.1 first converts amount/volume to binary float; converting that
    result to Decimal afterwards cannot restore the original monetary precision.
    Tencent returns up to 640 rows despite the requested dates, so select only
    the explicit range as AKShare does, without its start-year/fallback requests.
    """
    import requests
    import pandas as pd
    code=request['code'];symbol=('sh' if code.startswith('6') else 'sz')+code
    response=requests.get('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',
        params={'param':f"{symbol},day,{request['start']},{request['end']},640,"},timeout=15)
    response.raise_for_status();raw=response.json(parse_float=Decimal)['data'][symbol]['day']
    if not isinstance(raw,list) or len(raw)>10000:raise ValueError('Invalid daily shape')
    rows=[]
    with localcontext() as ctx:
        ctx.prec=80
        for row in raw:
            if not isinstance(row,list) or len(row)<9:raise ValueError('Invalid daily row')
            stamp=date.fromisoformat(row[0]).isoformat()
            if not request['start']<=stamp<=request['end']:continue
            rows.append({'日期':stamp,'开盘':row[1],'收盘':row[2],'最高':row[3],'最低':row[4],
                '成交量':format(Decimal(str(row[5]))*(1 if code.startswith('688') else 100),'f'),
                '成交额':format(Decimal(str(row[8]))*10000,'f')})
    return pd.DataFrame(rows)


def fetch(request):
    import akshare as ak
    source=request.get('source','eastmoney')
    if source not in ('eastmoney','tencent'):raise ValueError('Unsupported supplier')
    volume_unit='lots100'
    with single_attempt_pagination():
        if request['task']=='market':
            frame=(ak.stock_zh_a_spot_tx if source=='tencent' else ak.stock_zh_a_spot_em)()
            if frame.empty or len(frame)>8000:raise ValueError('Empty or oversized universe')
        elif source=='tencent':
            code=request['code']
            if request['kind']!='stock' or request['interval']!='day' or not code.startswith(('000','001','002','003','300','301','600','601','603','605','688')):
                raise ValueError('Tencent history supports declared Shanghai/Shenzhen stocks and daily bars only')
            frame=tencent_daily(request)
            volume_unit='shares'
        else:
            kind=request.get('kind','stock')
            if request['interval']=='day':
                loader=ak.stock_zh_a_hist if kind=='stock' else ak.fund_etf_hist_em
                frame=loader(symbol=request['code'],period='daily',start_date=request['start'].replace('-',''),end_date=request['end'].replace('-',''),adjust='',**({'timeout':15} if kind=='stock' else {}))
            else:
                loader=ak.stock_zh_a_hist_min_em if kind=='stock' else ak.fund_etf_hist_min_em
                frame=loader(symbol=request['code'],period='1',start_date=request['start']+' 09:30:00',end_date=request['end']+' 15:00:00',adjust='')
            if len(frame)>10000:raise ValueError('Oversized history')
    return {'rows':[{str(k):str(v) for k,v in row.items()} for row in frame.to_dict('records')],
            'library_version':ak.__version__,'upstream':source,'volume_unit':volume_unit,
            'adapter_version':'tencent-exact-v1' if source=='tencent' else 'akshare-selected-v1'}


if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.read(4096))
        with contextlib.redirect_stdout(io.StringIO()):result=fetch(request)
    except Exception as error:result=error_packet(error)
    sys.stdout.write(json.dumps(result,ensure_ascii=False,allow_nan=False))
