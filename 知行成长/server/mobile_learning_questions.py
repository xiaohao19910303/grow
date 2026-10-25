"""Stable exercise keys compatible with the H5 StudyNotes editor."""
import re


def questions(content):
    content=re.sub(r'<details\b[^>]*>.*?</details>','',content,flags=re.S|re.I)
    content=re.sub(r'^```.*?^```[^\n]*','',content,flags=re.S|re.M)
    excluded=0
    headings=list(re.finditer(r'^(#{2,6})\s+(.+?)\s*$',content,re.M));result=[]
    for i,h in enumerate(headings):
        title=re.sub(r'[*_`]', '',h[2]).strip()[:180]
        level=len(h[1])
        if excluded and level<=excluded:excluded=0
        if re.search(r'参考答案|参考分析|答案解析|答案与解释',title):excluded=level
        if excluded:continue
        if not re.search(r'练习|阅读理解|引导问题|思考题|思考问题|复盘问题',title) or re.search(r'参考答案|参考分析|答案解析|答案与解释',title):continue
        end=next((v.start() for v in headings[i+1:] if len(v[1])<=len(h[1])),len(content));section=content[h.end():end]
        if re.search(r'^#{2,6}\s+.*(?:练习|阅读理解|思考题)',section,re.M):continue
        prompts=re.findall(r'^\s*(?:[-*+] |\d+[.)] )(.+)$',section,re.M)
        if prompts and all(re.match(r'\[[ xX]\]',p) for p in prompts):continue
        if re.search(r'练习\s*[\d一二三四五六七八九十]',title) or not 1<=len(prompts)<=10:prompts=[title]
        for j,prompt in enumerate(prompts,1):result.append({'id':title+':'+str(j),'prompt':title+' · '+prompt[:700],'answer':''})
    return result[:100] or [{'id':'我的练习:1','prompt':'本课练习或应用思考','answer':''}]
