"""Deterministic comparisons of frozen research versions; no data-provider calls."""
import csv
import io
import json
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation,localcontext
import db
from fastapi import Header,Query
from fastapi.responses import Response
from pydantic import Field,model_validator
from copilot.core import fail,digest,encoded
from .contracts import Contract,Identifier
from .research_archive import ResearchArchive


def delta(left,right,allowed=True):
    if left is None or right is None or not allowed:return None
    try:
        a,b=Decimal(str(left)),Decimal(str(right))
        if not a.is_finite() or not b.is_finite() or max(len(a.as_tuple().digits),len(b.as_tuple().digits),abs(a.adjusted()),abs(b.adjusted()))>500:return None
        with localcontext() as ctx:
            ctx.prec=1100;result=format(b-a,'f')
        return result.rstrip('0').rstrip('.') if '.' in result else result
    except (InvalidOperation,ValueError):return None


def differences(left,right,allowed=True):
    return [{'field':key,'left':left.get(key),'right':right.get(key),'delta':delta(left.get(key),right.get(key),allowed)} for key in sorted(set(left)|set(right)) if left.get(key)!=right.get(key)]


def screen_result(left,right,left_dataset,right_dataset):
    a,b=left['data'],right['data'];la,rb=left_dataset['data'],right_dataset['data']
    rules=lambda d:{k:d['request'].get(k) for k in ('conditions','combine')}
    identity=lambda d:{'source':d.get('upstream') or d.get('source_label'),'units':d.get('source_units'), 'coverage':d.get('coverage'),'metrics_origin':d.get('metrics_origin')}
    same_data=a['dataset_hash']==b['dataset_hash'];same_rules=rules(a)==rules(b);same_source=identity(la)==identity(rb);same_algorithm=a.get('algorithm')==b.get('algorithm')
    comparable=same_algorithm and same_source and (same_data or same_rules)
    mode='same_snapshot' if same_data and same_rules else 'same_data_different_rules' if same_data else 'same_rules_different_dates' if same_rules and comparable else 'mixed_inputs'
    warnings=[] if comparable else ['数据、规则、来源、单位或算法同时变化；仅列事实差异，不能将变化归因于单一条件。']
    if la.get('market_date')==rb.get('market_date') and not same_data:warnings.append('同一数据日的不同快照，请核对采集时点及修订。')
    maps=[{r['code']:r for r in d['evaluations']} for d in (a,b)];changes=[]
    for code in sorted(set(maps[0])|set(maps[1])):
        x,y=maps[0].get(code),maps[1].get(code);ls=x['status'] if x else 'not_covered';rs=y['status'] if y else 'not_covered'
        category='coverage_added' if x is None else 'coverage_removed' if y is None else 'unknown_transition' if 'unknown' in (ls,rs) else 'retained' if ls==rs=='matched' else 'entered' if rs=='matched' else 'exited' if ls=='matched' else 'unchanged_excluded'
        changes.append({'code':code,'name':(y or x)['name'],'category':category,'left_status':ls,'right_status':rs,
            'left_details':x.get('details',[]) if x else [],'right_details':y.get('details',[]) if y else [],
            'value_changes':differences(x['values'] if x else {},y['values'] if y else {},comparable and x is not None and y is not None)})
    def context(d,s):return {k:s.get(k) for k in ('source_label','upstream','source_units','market_date','captured_at','coverage','actual_count','expected_count')}|{'request':d['request'],'algorithm':d.get('algorithm')}
    return {'kind':'screen','mode':mode,'comparable':comparable,'warnings':warnings,'left':context(a,la),'right':context(b,rb),'config_changes':differences(rules(a),rules(b),False),'summary':dict(Counter(r['category'] for r in changes)),'changes':changes}


def aligned_changes(left,right,keys,allowed=True):
    def mapping(rows):
        result={};counts=defaultdict(int)
        for row in rows:
            key=tuple(str(row.get(k,'')) for k in keys);counts[key]+=1;result[(*key,counts[key])]=row
        return result
    a,b=mapping(left),mapping(right);changes=[]
    for key in sorted(set(a)|set(b)):
        x,y=a.get(key),b.get(key)
        if x==y:continue
        changes.append({'category':'added' if x is None else 'removed' if y is None else 'changed','left':x,'right':y,'fields':differences(x or {},y or {},allowed)})
    return changes


def backtest_result(left,right,left_series,right_series):
    a,b=left['data'],right['data'];x,y=a['result'],b['result'];ca,cb=a['request']['config'],b['request']['config']
    same_history=a['series_hash']==b['series_hash'];same_algo=x.get('algorithm')==y.get('algorithm')
    base=('initial_cash','annual_periods','annual_risk_free');same_base=all(ca.get(k)==cb.get(k) for k in base)
    comparable=same_history and same_algo and same_base and x['status']==y['status']=='complete'
    warnings=[] if comparable else ['历史快照、基础资金/年化假设、算法或完整性不一致；不计算可归因的绩效差值。']
    metrics=[{'field':k,'left':(x.get('metrics') or {}).get(k),'right':(y.get('metrics') or {}).get(k),'delta':delta((x.get('metrics') or {}).get(k),(y.get('metrics') or {}).get(k),comparable)} for k in sorted(set(x.get('metrics') or {})|set(y.get('metrics') or {}))]
    trades=aligned_changes(x.get('trades',[]),y.get('trades',[]),('time','side','signal_at'),comparable)
    orders=aligned_changes(x.get('orders',[]),y.get('orders',[]),('signal_at','execution_at','side'),comparable)
    def context(d,s):return {'request':d['request'],'series_hash':d['series_hash'],'algorithm':d['result'].get('algorithm'),'status':d['result']['status'],'missing':d['result'].get('missing',[]),'history':{k:s['data'].get(k) for k in ('code','interval','price_basis','source_label','calendar_status')},'sensitivity':d.get('sensitivity',[]),'out_of_sample':({**{k:v for k,v in d['out_of_sample'].items() if k not in ('training','testing')},**{side:{k:v for k,v in d['out_of_sample'][side].items() if k not in ('equity','trades','orders')} for side in ('training','testing')}} if d.get('out_of_sample') else None)}
    summary=dict(Counter('trade_'+r['category'] for r in trades));summary.update(dict(Counter('order_'+r['category'] for r in orders)))
    reasons=lambda run:dict(Counter(r.get('reason','unknown') for r in run.get('orders',[])))
    return {'kind':'backtest','mode':'same_history' if same_history else 'different_history','comparable':comparable,'warnings':warnings,'left':context(a,left_series),'right':context(b,right_series),'config_changes':differences(ca,cb,False),'metrics':metrics,'summary':summary,'changes':trades,'order_changes':orders,'order_reasons':{'left':reasons(x),'right':reasons(y)}}


class ComparisonInput(Contract):
    account_id:Identifier
    left_id:Identifier
    left_version:int=Field(ge=1)
    right_id:Identifier
    right_version:int=Field(ge=1)
    name:str=Field(default='研究批次对比',min_length=1,max_length=100)
    @model_validator(mode='after')
    def distinct(self):
        if (self.left_id,self.left_version)==(self.right_id,self.right_version):raise ValueError('请选择两个不同的冻结版本。')
        return self


def compare(service,payload,key):
    archive=ResearchArchive(service);request=payload.model_dump(mode='json')
    with db.connect() as c:
        service.initialize(c)
        records=[archive.record(c,request[side+'_id'],request[side+'_version'],payload.account_id) for side in ('left','right')]
        if records[0]['kind']!=records[1]['kind'] or records[0]['kind'] not in ('screen','backtest'):fail('comparison_kind','请选择同类的两次筛选或两次回测。',422)
        parents=[archive.record(c,archive.parents(r)[0]['id'],archive.parents(r)[0]['version'],payload.account_id) for r in records]
        if any(p['input_hash']!=archive.parents(r)[0]['input_hash'] for r,p in zip(records,parents)):fail('comparison_reference','来源冻结哈希不一致。',409)
    result=(screen_result if records[0]['kind']=='screen' else backtest_result)(*records,*parents)
    data={'name':payload.name,'request':request,'algorithm':'frozen-research-comparison-v1','sources':[{k:r[k] for k in ('id','version','input_hash','kind')} for r in records],'result':result}
    return service.create('comparison',payload.account_id,data,key,digest(encoded({'comparison':request})))


def export_csv(record):
    result=record['data']['result'];output=io.StringIO();writer=csv.writer(output)
    def safe(value):
        text='null' if value is None else str(value);lead=text.lstrip('\ufeff \t\r\n')
        if lead.startswith(('=','+','@','-')) or text.startswith(('\t','\r','\n')):text="'"+text
        return text
    rows=[['对象','分类/指标','左值','右值','差值（右减左）']]
    if result['kind']=='screen':
        for row in result['changes']:
            rows.append([row['code'],row['category'],row['left_status'],row['right_status'],None])
            rows.extend([row['code'],v['field'],v['left'],v['right'],v['delta']] for v in row['value_changes'])
    else:
        rows.extend(['metrics',r['field'],r['left'],r['right'],r['delta']] for r in result['metrics'])
        for group in ('changes','order_changes'):
            for i,row in enumerate(result[group]):rows.append([group+':'+str(i),row['category'],json.dumps(row['left'],ensure_ascii=False),json.dumps(row['right'],ensure_ascii=False),None])
    for row in rows:writer.writerow([safe(v) for v in row])
    return '\ufeff'+output.getvalue()


def register(router,service):
    @router.post('/research/comparisons',status_code=201)
    def create(payload:ComparisonInput,idempotency_key:str=Header(alias='Idempotency-Key',min_length=8,max_length=160)):return compare(service,payload,idempotency_key)
    @router.get('/research/comparisons/{identity}/export')
    def export(identity:str,account_id:str,format:str=Query('json',pattern='^(json|csv)$')):
        with db.connect() as c:service.initialize(c);record=service.get(c,identity,'comparison',account_id)
        body=encoded(record) if format=='json' else export_csv(record)
        return Response(body,media_type='application/json' if format=='json' else 'text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="research-comparison.'+format+'"','Cache-Control':'no-store'})
