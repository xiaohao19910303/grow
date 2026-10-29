"""Public AKShare identifiers only; parent kills this worker on its fixed deadline."""
import contextlib
import io
import json
import sys


def fetch(request):
    import akshare as ak
    if request['task']=='market':
        frame=ak.stock_zh_a_spot_em()
        if len(frame)>8000:raise ValueError('Oversized universe')
    else:
        kind=request.get('kind','stock')
        if request['interval']=='day':
            loader=ak.stock_zh_a_hist if kind=='stock' else ak.fund_etf_hist_em
            frame=loader(symbol=request['code'],period='daily',start_date=request['start'].replace('-',''),end_date=request['end'].replace('-',''),adjust='',**({'timeout':15} if kind=='stock' else {}))
        else:
            loader=ak.stock_zh_a_hist_min_em if kind=='stock' else ak.fund_etf_hist_min_em
            frame=loader(symbol=request['code'],period='1',start_date=request['start']+' 09:30:00',end_date=request['end']+' 15:00:00',adjust='')
        if len(frame)>10000:raise ValueError('Oversized history')
    return {'rows':[{str(k):str(v) for k,v in row.items()} for row in frame.to_dict('records')], 'library_version':ak.__version__}


if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.read(4096))
        with contextlib.redirect_stdout(io.StringIO()):result=fetch(request)
    except ImportError:result={'error':'dependency_missing'}
    except Exception:result={'error':'upstream_unavailable'}
    sys.stdout.write(json.dumps(result,ensure_ascii=False,allow_nan=False))
