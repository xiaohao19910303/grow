"""选股规则v2：有限字段、交易日窗口、精确比较；不是回测或交易执行。"""
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import cmp_to_key
import re
from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


Identifier=Annotated[str,Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_.:-]+$')]

ALGORITHM='browser-screen-rational-v2'
PARSER='screen-rule-parser-v1'
FIELDS={
    'close':{'label':'收盘价','unit':'元','window':1},
    'turnover_cny':{'label':'当日成交额','unit':'元','window':1},
    'turnover_rate_pct':{'label':'当日换手率','unit':'%','window':1},
    'volume_ratio_5':{'label':'成交量/前5交易日均量','unit':'倍','window':6},
    'price_above_ma20':{'label':'收盘高于MA20','unit':'布尔','window':20}}
for n in (1,3,5,10,20):FIELDS[f'return_{n}d_pct']={'label':f'近{n}交易日价格变化','unit':'%','window':n+1}
for n in (3,5,10,20):FIELDS[f'avg_turnover_{n}d_pct']={'label':f'近{n}交易日平均换手率','unit':'%','window':n}
for n in (5,10,20):FIELDS[f'avg_amount_{n}d']={'label':f'近{n}交易日平均成交额','unit':'元','window':n}


def finite(value):
    if not isinstance(value,str) or len(value)>100:raise ValueError('阈值须为十进制字符串。')
    try:d=Decimal(value)
    except InvalidOperation as exc:raise ValueError('无效十进制数。') from exc
    if not d.is_finite() or abs(d)>=Decimal('1e20') or abs(d.as_tuple().exponent)>60:raise ValueError('阈值范围无效。')
    return d


class RuleCondition(Contract):
    field: str
    op: Literal['eq','ne','gt','gte','lt','lte','between']
    value: str = Field(max_length=100)
    upper_value: str | None = Field(default=None,max_length=100)

    @model_validator(mode='after')
    def bounded(self):
        if self.field not in FIELDS:raise ValueError('不支持的筛选字段。')
        if self.field=='price_above_ma20':
            if self.op not in ('eq','ne') or self.value not in ('true','false') or self.upper_value is not None:raise ValueError('均线条件需布尔比较。')
        else:
            low=finite(self.value)
            if self.op=='between':
                if self.upper_value is None or finite(self.upper_value)<low:raise ValueError('请核对包含上下界的区间。')
            elif self.upper_value is not None:raise ValueError('非区间条件不接收上界。')
        return self


class RuleScreen(Contract):
    as_of: date
    conditions: list[RuleCondition] = Field(default_factory=list,max_length=10)
    combine: Literal['all','any'] = 'all'
    sort_by: str = 'turnover_cny'
    descending: bool = True
    secondary_sort_by: str | None = None
    secondary_descending: bool = True
    limit: int = Field(default=20,ge=1,le=20)

    @model_validator(mode='after')
    def sorts(self):
        if self.sort_by not in FIELDS or (self.secondary_sort_by is not None and self.secondary_sort_by not in FIELDS):raise ValueError('排序字段无效。')
        return self


class RuleMapping(Contract):
    source: Literal['explicit','default','suggested']
    quote: str = Field(max_length=500)
    reason: str = Field(default='',max_length=500)


class RuleDraft(Contract):
    parser_version: Literal['screen-rule-parser-v1']
    screen: RuleScreen
    mappings: list[RuleMapping] = Field(max_length=10)
    sort_mapping: RuleMapping
    ambiguities: list[str] = Field(default_factory=list,max_length=10)
    unsupported: list[str] = Field(default_factory=list,max_length=10)

    @model_validator(mode='after')
    def mapped(self):
        if len(self.mappings)!=len(self.screen.conditions):raise ValueError('条件与原文对应数量不同。')
        if any(len(s)>500 for s in self.ambiguities+self.unsupported):raise ValueError('问题说明过长。')
        return self


class Generation(Contract):
    source_text: str = Field(min_length=1,max_length=2000)
    model: str = Field(min_length=1,max_length=100)
    parser_version: Literal['screen-rule-parser-v1']
    raw: str = Field(min_length=1,max_length=20000)
    draft: RuleDraft
    accepted_suggestions: bool
    issues_resolved: bool


class ScreeningTemplate(Contract):
    account_id: Identifier
    name: str = Field(min_length=1,max_length=100)
    description: str = Field(default='',max_length=2000)
    instrument_ids: list[Identifier] = Field(min_length=1,max_length=20)
    screen: RuleScreen
    enabled: bool = True
    generation: Generation | None = None

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.instrument_ids))!=len(self.instrument_ids):raise ValueError('股票池不能重复。')
        if self.generation:
            g=self.generation
            validate_draft(g.draft,g.source_text)
            if not g.accepted_suggestions or not g.issues_resolved:raise ValueError('请先核对并处理生成草稿。')
        return self


def validate_draft(draft,text):
    for m in [*draft.mappings,draft.sort_mapping]:
        if m.quote and m.quote not in text:raise ValueError('条件对应片段不属于原文。')
        if m.source=='explicit' and not m.quote:raise ValueError('原文明确条件须有原文片段。')
        if m.source=='suggested' and not m.reason:raise ValueError('AI建议须说明原因。')
    for c,m in zip(draft.screen.conditions,draft.mappings):
        if m.source=='explicit':validate_explicit(c.model_dump(),m.quote)


def validate_explicit(c,quote):
    if c['field']=='price_above_ma20':return
    cleaned=re.sub(r'(\d)\s*[-—–～]\s*(?=\d)',r'\1~',quote)
    numbers=[]
    for match in re.finditer(r'[+-]?\d+(?:\.\d+)?\s*(?:亿元|万元|亿|万|元|%|％|倍)?',cleaned):
        if re.match(r'\s*(?:个)?(?:交易日|日|天)',cleaned[match.end():]) or cleaned[max(0,match.start()-2):match.start()].upper()=='MA':continue
        token=match.group().strip();n=re.match(r'[+-]?\d+(?:\.\d+)?',token).group()
        numbers.append(Decimal(n)*(Decimal('100000000') if '亿' in token else Decimal('10000') if '万' in token else 1))
    # 中文纯文字阈值保留给人工核对；有明确数字时不允许模型改写成别的阈值。
    if numbers and (finite(c['value']) not in numbers or (c['op']=='between' and finite(c['upper_value']) not in numbers)):
        raise ValueError('生成阈值与原文数值或单位不一致。')
    is_range=len(numbers)==2 and bool(re.search('到|至|~|之间',cleaned))
    if is_range and (c['op']!='between' or finite(c['value'])!=numbers[0] or finite(c['upper_value'])!=numbers[1]):
        raise ValueError('原文区间边界不得省略或调整。')
    if len(numbers)==1 and c['op']=='between':raise ValueError('原文单个阈值不能擅自补成区间。')
    lower=bool(re.search('至少|不低于|不少于|大于等于|以上',quote));upper=bool(re.search('不超过|不高于|不大于|小于等于|以下',quote))
    if lower and not upper and c['op']!='gte':raise ValueError('原文下界应包含等于。')
    if upper and not lower and c['op']!='lte':raise ValueError('原文上界应包含等于。')
    if not lower and not upper:
        if re.search('超过|大于|高于',quote) and c['op']!='gt':raise ValueError('原文为严格大于。')
        if re.search('低于|小于',quote) and c['op']!='lt':raise ValueError('原文为严格小于。')
    window=re.search(r'近\s*(\d+)\s*(?:个)?(?:交易日|日|天)',quote)
    chosen=re.search(r'_(\d+)d',c['field'])
    if window and chosen and int(window[1])!=int(chosen[1]):raise ValueError('生成窗口与原文不一致。')


def turnover_value(value):
    # 换手率为数值百分比；缺项不补0，超过100不自动视为错误。
    if value is None or str(value).strip().lower() in ('','nan','none','--','null'):return None
    d=finite(str(value))
    if d<0:raise ValueError('换手率不能为负数。')
    return format(d,'f')


def display(value):
    if value is None or isinstance(value,bool):return value
    negative=value<0;value=abs(value);scaled=value.numerator*10**28//value.denominator
    whole,rest=divmod(scaled,10**28);tail=str(rest).zfill(28).rstrip('0')
    return ('-' if negative and scaled else '')+str(whole)+('.'+tail if tail else '')


def evaluate_item(item,request):
    bars=sorted([b for b in item['bars'] if b['date']<=request['as_of']],key=lambda b:b['date'])
    by_date={b['date']:b for b in bars};cal=item.get('calendar',{})
    sessions=sorted(d for d,opened in cal.get('sessions',{}).items() if opened and d<=request['as_of'])
    values={};reasons={};numeric={}
    for field,meta in FIELDS.items():
        reason=None;v=None;n=meta['window'];days=sessions[-n:]
        if cal.get('status')!='available':reason='日历未覆盖或已过复核期'
        elif not days or days[-1]!=request['as_of']:reason='目标数据日不是已核对交易日'
        elif item.get('price_basis') not in ('unadjusted','unadjusted_user_declared'):reason='价格口径未知或不一致'
        elif request['as_of'] not in by_date:reason='目标日行情缺失或过期'
        elif len(days)<n or any(d not in by_date for d in days):reason='所需交易日记录不足'
        else:
            window=[by_date[d] for d in days]
            try:
                f=lambda b,k:Fraction(Decimal(b[k]))
                if field=='close':v=f(window[-1],'close')
                elif field=='turnover_cny':v=f(window[-1],'turnover_cny')
                elif field=='turnover_rate_pct':v=f(window[-1],'turnover_rate_pct')
                elif field.startswith('return_'):v=(f(window[-1],'close')/f(window[0],'close')-1)*100
                elif field.startswith('avg_turnover_'):v=sum((f(b,'turnover_rate_pct') for b in window),Fraction(0))/n
                elif field.startswith('avg_amount_'):v=sum((f(b,'turnover_cny') for b in window),Fraction(0))/n
                elif field=='volume_ratio_5':v=f(window[-1],'volume_shares')*5/sum((f(b,'volume_shares') for b in window[:-1]),Fraction(0))
                else:v=f(window[-1],'close')*20>sum((f(b,'close') for b in window),Fraction(0))
            except (KeyError,TypeError,ValueError,ArithmeticError):reason='所需字段缺失或分母无效'
        values[field]=display(v);numeric[field]=v;reasons[field]=reason
    outcomes=[];details=[]
    for c in request['conditions']:
        v=numeric[c['field']];result=None
        if v is not None:
            b=(c['value']=='true') if isinstance(v,bool) else Fraction(finite(c['value']))
            op=c['op']
            result= b<=v<=Fraction(finite(c['upper_value'])) if op=='between' else {'eq':v==b,'ne':v!=b,'gt':v>b,'gte':v>=b,'lt':v<b,'lte':v<=b}[op]
        outcomes.append(result);details.append({'field':c['field'],'actual':values[c['field']],'result':result,'reason':reasons[c['field']],'unit':FIELDS[c['field']]['unit']})
    if request['combine']=='all':status='excluded' if False in outcomes else 'unknown' if None in outcomes else 'matched'
    else:status='matched' if True in outcomes else 'unknown' if None in outcomes else 'excluded'
    if not outcomes:status='matched' if numeric['close'] is not None else 'unknown'
    return {'instrument_id':item['instrument_id'],'code':item['code'],'name':item['name'],'data_date':request['as_of'] if request['as_of'] in by_date else None,
        'values':values,'condition_results':outcomes,'details':details,'status':status},numeric


def screen_v2(bundle):
    request=RuleScreen.model_validate(bundle['request']).model_dump(mode='json');pairs=[evaluate_item(i,request) for i in bundle['universe']]
    def compare(a,b):
        for field,desc in [(request['sort_by'],request['descending']),(request['secondary_sort_by'],request['secondary_descending'])]:
            if field:
                x,y=a[1][field],b[1][field]
                result=(1 if x is None else -1) if (x is None)!=(y is None) else 0 if x==y else (-1 if x<y else 1)*(-1 if desc else 1)
                if result:return result
        return (a[0]['code']>b[0]['code'])-(a[0]['code']<b[0]['code'])
    matched=sorted([p for p in pairs if p[0]['status']=='matched'],key=cmp_to_key(compare))
    return {'algorithm':ALGORITHM,'items':[p[0] for p in matched[:request['limit']]],'evaluations':[p[0] for p in pairs],
        'total':len(matched),'unresolved':sum(p[0]['status']=='unknown' for p in pairs)}
