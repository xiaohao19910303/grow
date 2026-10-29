"""One bounded AKShare call in a disposable process; public identifiers only."""
import contextlib
import io
import json
import sys


def fetch(request):
    import akshare as ak
    from importlib.metadata import version
    # 东方财富盘后日线：只调用已选品种接口，不取账户资料、不自动换源或复权。
    loaders={'stock':ak.stock_zh_a_hist,'etf':ak.fund_etf_hist_em}
    frame=loaders[request['kind']](symbol=request['code'],period='daily',
        start_date=request['start'].replace('-',''),end_date=request['end'].replace('-',''),adjust='',
        **({'timeout':15} if request['kind']=='stock' else {}))
    columns=['日期','开盘','最高','最低','收盘','成交量','成交额']
    if len(frame)>200 or (not frame.empty and not set(columns).issubset(frame.columns)):
        raise ValueError('Unexpected daily columns or size')
    if request['kind']=='stock' and '换手率' in frame.columns:columns.append('换手率')
    rows=[] if frame.empty else [{key:str(value) for key,value in row.items()}
        for row in frame[columns].to_dict(orient='records')]
    return {'rows':rows,'library_version':version('akshare')}


if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.read(4096))
        with contextlib.redirect_stdout(io.StringIO()):
            result=fetch(request)
    except ImportError:
        result={'error':'dependency_missing'}
    except Exception:
        result={'error':'upstream_unavailable'}
    sys.stdout.write(json.dumps(result,ensure_ascii=False,allow_nan=False))
