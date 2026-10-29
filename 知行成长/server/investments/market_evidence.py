"""Bounded daily excerpts and literal quotation hints; no new data or corrections."""
import json
import re


def daily_excerpt(bars):
    # 行情摘要范围：只裁剪发送正文，指标仍由调用方基于全部已保存输入计算。
    shown=bars[-20:]
    omitted=len(bars)-len(shown)
    return {'bars':shown,'omitted_bar_count':omitted,
        'summary_scope':{'stored_bar_count':len(bars),'included_bar_count':len(shown),
            'summary_omitted_bar_count':omitted,'omission_reason':'recent_20_bars_only',
            'indicator_input_bar_count':len(bars),
            'indicator_scope':'all_stored_input_bars_with_per_indicator_lookbacks',
            'indicator_windows':{field:{'required_input_records':required,
                'stored_record_count_sufficient':len(bars)>=required,
                'summary_record_count_sufficient':len(shown)>=required}
                for field,required in (('ma5',5),('ma20',20),('volume_ratio_5',6),('atr14',15),('record_return_std20',21))},
            'source_completeness':'not_independently_verified',
            'explanation':'省略仅指发送摘要未逐条展示较早记录，不代表源数据缺失或指标少用记录；'
                '无法在当前摘要独立复算不等于指标缺输入；已保存条数也不证明应有交易日齐全。'}}


def quotation_hints(content):
    # 原文引用提示：只提取选定行情正文的连续子串，不补零、不四舍五入或改写正文。
    try:
        data=json.loads(content)
    except (ValueError,TypeError):
        return []
    if not isinstance(data,dict) or not isinstance(data.get('bars'),list) or not isinstance(data.get('indicators'),dict):
        return []
    hints=[]
    for field in ('close','ma5','ma20','volume_ratio_5','price_basis','latest_session'):
        pattern=r'"'+field+r'"\s*:\s*(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
        matches=list(re.finditer(pattern,content))
        if matches:
            quote=matches[-1].group()
            if len(quote)<=500:
                hints.append({'field':field,'quote':quote})
    return hints
