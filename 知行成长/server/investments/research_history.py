"""Historical source capture and immutable backtest runs share the research store."""
import csv
import io
from datetime import date,datetime
from decimal import Decimal,localcontext
from typing import Literal
from zoneinfo import ZoneInfo

import db
from fastapi import Header
from pydantic import AwareDatetime,Field,StrictBool,model_validator
from copilot.core import digest,encoded,fail,now
from .contracts import Contract,Identifier
from .market_data import canonical_code
from .rule_screening import finite
from .rules import calendar
from .strategy_backtest import BacktestConfig,backtest


class HistoricalBar(Contract):
    time:AwareDatetime
    open_at:AwareDatetime|None=None
    available_at:AwareDatetime|None=None
    open:str;high:str;low:str;close:str
    volume_shares:str
    turnover_cny:str|None=None
    suspended:StrictBool|None=None
    limit_up:str|None=None
    limit_down:str|None=None
    corporate_actions_known:StrictBool|None=None
    adj_factor:str|None=None
    split_ratio:str='1'
    cash_dividend:str='0'
    benchmark_close:str|None=None
    @model_validator(mode='after')
    def valid(self):
        for field in ('open','high','low','close','adj_factor','split_ratio','limit_up','limit_down','benchmark_close'):
            value=getattr(self,field)
            if value is not None and finite(value)<=0:raise ValueError('行情价格或因子须为正。')
        for field in ('volume_shares','turnover_cny','cash_dividend'):
            value=getattr(self,field)
            if value is not None and finite(value)<0:raise ValueError('量额不能为负。')
        if not finite(self.low)<=min(finite(self.open),finite(self.close))<=max(finite(self.open),finite(self.close))<=finite(self.high):raise ValueError('OHLC冲突。')
        if self.open_at and self.open_at>self.time:raise ValueError('开盘不能晚于收盘。')
        if self.available_at and self.available_at<self.time:raise ValueError('完整收盘数据不可提前获知。')
        return self


class SeriesInput(Contract):
    account_id:Identifier
    code:str=Field(max_length=20)
    name:str=Field(min_length=1,max_length=100)
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool
    interval:Literal['day','minute']='day'
    price_basis:Literal['unadjusted','adjusted','unknown']='unknown'
    sessions:list[date]=Field(default_factory=list,max_length=4000)
    expected_bar_times:list[AwareDatetime]=Field(default_factory=list,max_length=10000)
    benchmark_label:str|None=Field(default=None,max_length=200)
    bars:list[HistoricalBar]=Field(min_length=1,max_length=10000)
    @model_validator(mode='after')
    def valid(self):
        canonical_code(self.code)
        if not self.use_confirmed:raise ValueError('需确认来源。')
        if len({b.time for b in self.bars})!=len(self.bars):raise ValueError('行情时间重复。')
        return self


class SeriesCSV(Contract):
    account_id:Identifier
    code:str=Field(max_length=20)
    name:str=Field(min_length=1,max_length=100)
    source_label:str=Field(min_length=1,max_length=300)
    use_confirmed:StrictBool
    interval:Literal['day','minute']='day'
    price_basis:Literal['unadjusted','adjusted','unknown']='unknown'
    sessions:list[date]=Field(default_factory=list,max_length=4000)
    expected_bar_times:list[AwareDatetime]=Field(default_factory=list,max_length=10000)
    text:str=Field(min_length=1,max_length=4000000,repr=False)


class BacktestInput(Contract):
    account_id:Identifier
    series_id:Identifier
    config:BacktestConfig
    out_of_sample_start:date|None=None
    variants:list[dict]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def valid(self):
        allowed={'fast_window','slow_window','slippage_bps','commission_rate','entry_above','exit_below'}
        for variant in self.variants:
            if not variant or not set(variant)<=allowed:raise ValueError('参数试验只接受有限数值参数。')
            BacktestConfig.model_validate({**self.config.model_dump(),**variant})
        return self


def timestamp(value,day=False):
    if len(value)==10:return value+('T15:00:00+08:00' if day else 'T00:00:00+08:00')
    parsed=datetime.fromisoformat(value.replace(' ','T'))
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    return parsed.isoformat()


def parse_csv(payload):
    reader=csv.DictReader(io.StringIO(payload.text));rows=[]
    if not reader.fieldnames or len(reader.fieldnames)>30:fail('csv_fields','CSV表头缺失或字段过多。',422)
    for raw in reader:
        if len(rows)>=10000:fail('csv_size','历史输入最多10000根。',422)
        row={k:v.strip() for k,v in raw.items() if k and isinstance(v,str) and v.strip()}
        if 'date' in row:row['time']=row.pop('date')
        try:
            row['time']=timestamp(row['time'],payload.interval=='day')
            for name in ('open_at','available_at'):
                if name in row:row[name]=timestamp(row[name])
            for name in ('suspended','corporate_actions_known'):
                if name in row:
                    if row[name].lower() not in ('true','false','1','0'):raise ValueError()
                    row[name]=row[name].lower() in ('true','1')
            rows.append(HistoricalBar.model_validate(row))
        except (ValueError,TypeError,KeyError):fail('csv_row',f'第{len(rows)+2}行格式无效，请核对时间、OHLC及规则字段。',422)
    return SeriesInput(**payload.model_dump(exclude={'text'}),bars=rows)


def save_series(service,payload,key,metadata=None,fingerprint=None):
    instant=datetime.fromisoformat(now());data=payload.model_dump(mode='json',exclude={'account_id','use_confirmed'})
    if any(b.time>instant or (b.available_at and b.available_at>instant) for b in payload.bars):fail('future_data','不能保存未来行情或尚不可知的资料。',422)
    data['code']=canonical_code(payload.code);data['bars'].sort(key=lambda b:datetime.fromisoformat(b['time']))
    if payload.interval=='day' and len({b.time.astimezone(ZoneInfo('Asia/Shanghai')).date() for b in payload.bars})!=len(payload.bars):fail('duplicate_session','日线同一交易日只能有一根。',422)
    if not data['sessions']:
        days=[b.time.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() for b in payload.bars]
        reference=calendar({'SH':'SSE','SZ':'SZSE','BJ':'BSE'}[data['code'][-2:]],min(days),max(days),now()) if (date.fromisoformat(max(days))-date.fromisoformat(min(days))).days<=369 else {'status':'coverage_unknown','sessions':{}}
        data['sessions']=[d for d,opened in reference['sessions'].items() if opened] if reference['status']=='available' else []
        data['calendar_status']=reference['status']
    else:data['calendar_status']='user_declared'
    data.update(captured_at=now(),source_verification='user_declared',**(metadata or {}))
    return service.create('series',payload.account_id,data,key,fingerprint or digest(encoded({'series':payload.model_dump(mode='json'),'metadata':metadata})))


def run_backtest(service,payload,key):
    with db.connect() as c:
        service.initialize(c);source=service.get(c,payload.series_id,'series',payload.account_id)
    series=source['data'];base=backtest(series,payload.config)
    if base['metrics'] is not None:
        benchmark=[b.get('benchmark_close') for b in series['bars']]
        if series.get('benchmark_label') and benchmark and all(benchmark):
            with localcontext() as ctx:
                ctx.prec=60
                base['metrics']['benchmark_return_pct']=str((Decimal(benchmark[-1])/Decimal(benchmark[0])-1)*100)
            base['metrics']['benchmark_label']=series['benchmark_label']
    sensitivity=[]
    for variant in payload.variants:
        config=BacktestConfig.model_validate({**payload.config.model_dump(),**variant});result=backtest(series,config)
        sensitivity.append({'config':config.model_dump(mode='json'),'status':result['status'],'metrics':result['metrics'],'missing':result['missing']})
    split=None
    if payload.out_of_sample_start:
        pivot=payload.out_of_sample_start
        training=[b for b in series['bars'] if datetime.fromisoformat(b['time']).astimezone(ZoneInfo('Asia/Shanghai')).date()<pivot]
        testing=[b for b in series['bars'] if datetime.fromisoformat(b['time']).astimezone(ZoneInfo('Asia/Shanghai')).date()>=pivot]
        if not training or not testing:fail('sample_split','样本外分割须在输入区间内部，保留训练和测试资料。',422)
        split={'start':pivot.isoformat(),'parameter_selection':'user_selected_before_run','positions_carried':False,
            'training':backtest(series,payload.config,end_at=datetime.fromisoformat(training[-1]['time']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()),
            'testing':backtest(series,payload.config,start_at=pivot.isoformat())}
    data={'request':payload.model_dump(mode='json'),'series_hash':source['input_hash'],'result':base,'sensitivity':sensitivity,'out_of_sample':split}
    return service.create('backtest',payload.account_id,data,key)


def register(router,service):
    @router.post('/research/series',status_code=201)
    def series(payload:SeriesInput,idempotency_key:str=Header(min_length=8,max_length=160)):return save_series(service,payload,idempotency_key)
    @router.post('/research/series/csv',status_code=201)
    def series_csv(payload:SeriesCSV,idempotency_key:str=Header(min_length=8,max_length=160)):return save_series(service,parse_csv(payload),idempotency_key)
    @router.post('/research/backtests',status_code=201)
    def run(payload:BacktestInput,idempotency_key:str=Header(min_length=8,max_length=160)):return run_backtest(service,payload,idempotency_key)
