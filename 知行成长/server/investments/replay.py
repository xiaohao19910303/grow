"""Declared one-minute paths for retrospective ledger review, never simulated fills."""
import csv
import io
import json
from datetime import datetime,timedelta,time
from decimal import Decimal,localcontext
from zoneinfo import ZoneInfo
import db
from pydantic import AwareDatetime,Field,StrictBool,ValidationError,StringConstraints
from typing import Literal,Annotated
from copilot.core import digest,encoded,fail,now
from .contracts import Contract,Identifier,Positive,Money
from .accounting import reconcile,number
from .rules import calendar,normalize_units

TZ=ZoneInfo('Asia/Shanghai')

class PathInput(Contract):
    account_id: Identifier
    instrument_id: Identifier
    text: Annotated[str,StringConstraints(strip_whitespace=False)] = Field(min_length=1,max_length=250000)
    source_label: str = Field(min_length=1,max_length=100)
    source_note: str = Field(default='',max_length=2000)
    volume_unit: Literal['shares','lots100']
    amount_unit: Literal['cny','thousand_cny']
    price_basis: Literal['unadjusted']
    use_confirmed: StrictBool

class Bar(Contract):
    start: AwareDatetime
    open: Positive
    high: Positive
    low: Positive
    close: Positive
    volume: Money
    amount: Money


def stamp(value):
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None:raise ValueError('时间须含时区。')
    return parsed.astimezone(TZ)

def regular(start):
    end=start+timedelta(minutes=1)
    return start.date()==end.date() and ((time(9,30)<=start.time() and end.time()<=time(11,30)) or (time(13)<=start.time() and end.time()<=time(15)))


def import_path(store,payload,key):
    try:data=PathInput.model_validate(payload).model_dump(mode='json')
    except ValidationError:fail('invalid_path','请核对账户、证券、来源、未复权口径、单位及分钟CSV。',422)
    if not data['use_confirmed'] or len(data['text'].encode('utf-8'))>250000:
        fail('invalid_path','请本人确认来源用途及半开区间的一分钟数据；文件不能超过250KB。',422)
    fingerprint=digest(encoded({'path_import':data}));rid='path-'+fingerprint
    with db.connect() as c:
        store.lock(c);old=store.replay(c,key,fingerprint)
        if old is not None:return old
        store._get(c,'accounts',data['account_id']);instrument=store._get(c,'instruments',data['instrument_id'])
        if instrument['market'] not in ('SSE','SZSE') or instrument['kind'] not in ('stock','etf'):
            fail('unsupported_path','当前仅接收沪深股票/ETF普通竞价时段的一分钟路径。',422)
        existing=c.execute("SELECT data FROM investment_objects WHERE id=? AND kind='intraday-paths'",(rid,)).fetchone()
        if existing:
            record=json.loads(existing[0]);store.remember(c,key,fingerprint,record);return record
        bars=[];created=now();previous=None
        try:
            reader=csv.DictReader(io.StringIO(data['text'].lstrip('\ufeff')))
            required={'start','open','high','low','close','volume','amount'}
            if set(reader.fieldnames or [])!=required or len(reader.fieldnames)!=7:raise ValueError()
            for index,row in enumerate(reader):
                if index>=2000:raise ValueError()
                bar=Bar.model_validate(row).model_dump(mode='json');start=stamp(bar['start']);end=start+timedelta(minutes=1)
                if start.second or start.microsecond or not regular(start) or end>stamp(created) or (previous and start<previous):raise ValueError()
                if not Decimal(bar['low'])<=min(Decimal(bar['open']),Decimal(bar['close']))<=max(Decimal(bar['open']),Decimal(bar['close']))<=Decimal(bar['high']):raise ValueError()
                bars.append({**{k:bar[k] for k in ('open','high','low','close')},'start':start.isoformat(),'end':end.isoformat(),
                    **normalize_units(bar['volume'],bar['amount'],data['volume_unit'],data['amount_unit'])})
                previous=end
            if not bars:raise ValueError()
        except (ValidationError,ValueError,TypeError,csv.Error):
            fail('invalid_path_csv','请使用顺序且不重叠的一分钟起点（含时区）、有效OHLC/量额；不能含未来、午休或盘后窗口。',422)
        try:cal=calendar(instrument['market'],bars[0]['start'][:10],bars[-1]['start'][:10],created)
        except ValueError:cal={'status':'coverage_unknown','sessions':{}}
        if cal['status']=='available' and any(not cal['sessions'][b['start'][:10]] for b in bars):
            fail('closed_path_session','分钟路径包含公开参考日历的休市日，请核对来源。',422)
        record={k:v for k,v in data.items() if k!='text'}
        record.update(id=rid,version=1,created_at=created,updated_at=created,bars=bars,calendar_snapshot=cal,
            raw_text=data['text'],
            source_hash=digest(data['text']),interval='[start,start+1 minute)',scope='auction_regular_only',
            source_independently_verified=False,realtime=False)
        record['snapshot_hash']=digest(encoded(record));store.save(c,'intraday-paths',record,fresh=True)
        store.remember(c,key,fingerprint,record);return record


def paths(store,account_id,instrument_id=None,page=1):
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        where="kind='intraday-paths' AND data::jsonb->>'account_id'=?";args=[account_id]
        if instrument_id:where+=" AND data::jsonb->>'instrument_id'=?";args.append(instrument_id)
        total=c.execute('SELECT count(*) FROM investment_objects WHERE '+where,args).fetchone()[0]
        rows=c.execute("SELECT (data::jsonb-'bars'-'calendar_snapshot'-'raw_text')::text FROM investment_objects WHERE "+where+' ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?',(*args,(page-1)*50))
        return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'page_size':50}


def replay_campaign(store,account_id,campaign_id,path_id,cutoff=None):
    as_of=cutoff or now()
    try:
        end=stamp(as_of)
        if end>stamp(now()):raise ValueError()
    except (ValueError,TypeError):fail('invalid_replay_cutoff','回放截止时间须带时区且不能晚于当前时间。',422)
    with db.connect() as c,localcontext() as ctx:
        ctx.prec=60;store.lock(c);account=store._get(c,'accounts',account_id)
        path=store._get(c,'intraday-paths',path_id)
        campaign=next((x for x in store._campaigns(c,account_id) if x['id']==campaign_id),None)
        if not campaign or path['account_id']!=account_id or path['instrument_id']!=campaign['instrument_id']:
            fail('scope_mismatch','路径与交易链不属于同一账户/证券。',422)
        opening=[p for p in account['opening_positions'] if p['instrument_id']==campaign['instrument_id']] if campaign_id.startswith('opening-') else []
        fills=[f for f in campaign['fills'] if stamp(f['executed_at'])<=end]
        if not fills and not opening:fail('replay_before_entry','截止时间早于所录入场。',422)
        if len(fills)>500:fail('replay_too_many_fills','单次路径复盘最多500笔成交，请缩小截止范围。',422)
        started=stamp(fills[0]['executed_at']) if not opening else stamp(account['baseline_date']+'T00:00:00+08:00')
        if end<started:fail('replay_before_entry','截止时间早于核对起点。',422)
        final=reconcile('0',[],fills,opening_positions=opening)
        quantity=sum((Decimal(p['quantity']) for p in opening),Decimal('0'))+sum((Decimal(f['quantity'])*(1 if f['side']=='buy' else -1) for f in fills),Decimal('0'))
        if not quantity and fills:end=min(end,stamp(fills[-1]['executed_at']))
        if end-started>timedelta(days=62):fail('replay_range_too_large','单次路径复盘最多覆盖62个自然日，请缩小截止范围。',422)
        available={b['start']:b for b in path['bars'] if stamp(b['end'])<=end}
        conflicts=[]
        for fill in fills:
            key=stamp(fill['executed_at']).replace(second=0,microsecond=0).isoformat();bar=available.get(key)
            if bar and not Decimal(bar['low'])<=Decimal(fill['price'])<=Decimal(bar['high']):
                conflicts.append({'fill_id':fill['id'],'minute':key,'reason':'成交价不在对应分钟高低价范围内'})
            if bar and Decimal(fill['quantity'])>Decimal(bar['volume_shares']):
                conflicts.append({'fill_id':fill['id'],'minute':key,'reason':'单笔实际数量超过所声明分钟成交量，请核对单位或成交时点'})
        sessions=path['calendar_snapshot'].get('sessions',{});calendar_known=path['calendar_snapshot']['status']=='available'
        rows=[];expected=0;missing=[];missing_count=0;boundary=0;prefix=[];cursor=0;state=None
        values=[Decimal('0')];fees_known=final['fees_complete'] and final.get('settlements_complete',True)
        t=started.replace(second=0,microsecond=0)
        while t<end:
            while cursor<len(fills) and stamp(fills[cursor]['executed_at'])<=t:
                prefix.append(fills[cursor]);cursor+=1;state=None
            if state is None:state=reconcile('0',[],prefix,opening_positions=opening)
            current_position=next((p for p in state['positions'] if p['instrument_id']==campaign['instrument_id']),None)
            q=Decimal(current_position['quantity']) if current_position else Decimal('0')
            inside=cursor<len(fills) and t<stamp(fills[cursor]['executed_at'])<t+timedelta(minutes=1)
            if regular(t) and (q>0 or inside):
                day=t.date().isoformat()
                if day not in sessions:calendar_known=False
                if sessions.get(day) is not False:
                    expected+=1
                    if inside or t+timedelta(minutes=1)>end:boundary+=1
                    else:
                        bar=available.get(t.isoformat())
                        if bar is None:
                            missing_count+=1
                            if len(missing)<20:missing.append(t.isoformat())
                        else:
                            position=next((p for p in state['positions'] if p['instrument_id']==campaign['instrument_id']),None)
                            lower=upper=None
                            if position and state['fees_complete'] and state['net_realized'] is not None and position['cost'] is not None:
                                lower=Decimal(state['net_realized'])+q*Decimal(bar['low'])-Decimal(position['cost'])
                                upper=Decimal(state['net_realized'])+q*Decimal(bar['high'])-Decimal(position['cost'])
                                values.extend([lower,upper])
                            rows.append({**{k:bar[k] for k in ('start','end','open','high','low','close')},'quantity':number(q),
                                'cost':position['cost'] if position else None,'lower_pnl':number(lower),'upper_pnl':number(upper)})
            t+=timedelta(minutes=1)
        # Actual transaction marks and final realized values are evidence too, but do not fill path gaps.
        for index,f in enumerate(fills):
            marked=reconcile('0',[],fills[:index+1],opening_positions=opening,marks={campaign['instrument_id']:f['price']})
            if marked['net_realized'] is not None and marked['fees_complete']:
                unreal=sum((Decimal(p['unrealized']) for p in marked['positions'] if p['unrealized'] is not None),Decimal('0'))
                values.append(Decimal(marked['net_realized'])+unreal)
        ledger_verified=fees_known and not campaign.get('reconciliation_required')
        verified=ledger_verified and not conflicts
        complete=bool(rows) and calendar_known and not missing_count and not boundary and not opening and verified
        result={'account_id':account_id,'campaign_id':campaign_id,'path_id':path_id,'cutoff':as_of,
            'status':'complete_declared_path' if complete else 'incomplete_or_unverified','retrospective':True,'realtime':False,
            'information_mode':'retrospective_current_ledger','not_point_in_time_backtest':True,'source_independently_verified':False,
            'mae_cash':number(min(values)) if complete else None,'mfe_cash':number(max(values)) if complete else None,
            'observed_mae_cash':number(min(values)) if verified else None,'observed_mfe_cash':number(max(values)) if verified else None,
            'actual_net_realized':final['net_realized'] if ledger_verified else None,'actual_fill_count':len(fills),'open_at_cutoff':quantity>0,
            'fact_conflict_count':len(conflicts),'fact_conflicts':conflicts[:20],
            'coverage':{'expected_minutes':expected if calendar_known else None,'usable_minutes':len(rows),'missing_minutes':missing_count if calendar_known else None,
                'boundary_minutes':boundary,'missing_examples':missing,'calendar_verified_subset':calendar_known},'rows':rows,
            'path_hash':path['snapshot_hash'],'ledger_hash':digest(encoded({'opening':opening,'fills':fills})),
            'formula':'各分钟成交已实现净结果 + 当时剩余数量×分钟高/低价 - 当时剩余移动加权成本；含已记成交费用，不含分红、利息、独立账户费用或未来假设退出费用。',
            'limitations':['本人声明的一分钟未复权路径，只覆盖普通竞价；不是逐笔路径、可成交证明或未来回测。',
                '期初仓位、缺分钟、分钟内变动、未知费用或账实差异时，完整MAE/MFE为空；仅展示已观察边界。',
                '当前账本更正用于事后复盘，不宣称这些资料在交易当时已知；原路径与账本哈希保留。',
                '高低价先后未知，不推导止损/目标成交顺序；剩余仓位按同一证券价格标记不代表可按该价格全部成交。']}
        if not verified:
            for row in rows:
                row.update(lower_pnl=None,upper_pnl=None)
                if not ledger_verified:row['cost']=None
        result['result_hash']=digest(encoded(result));return result
