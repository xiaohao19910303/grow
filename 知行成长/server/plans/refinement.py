"""Immutable draft contents, explicit scope validation and deterministic merging."""
import copy
import re
from copilot.core import digest, encoded, fail

FIELDS = {'topic','goal','exercise','assessment','minutes','stage','kind','requires'}


def payload(d):
    keys = ('brief','document','plan_id','base_version','overrides') if d['kind']=='plan' else ('context','content','sources','complete')
    return {k:d.get(k) for k in keys}


def content_hash(d):
    return digest(encoded(payload(d)))


def sections(content):
    # Only unambiguous H2 sections outside fenced code; prefix protects date and title.
    matches=[]; offset=0; fence=None
    for line in content.splitlines(keepends=True):
        marker=re.match(r'^\s{0,3}(`{3,}|~{3,})',line)
        if marker:
            char=marker[1][0]
            if fence is None: fence=char
            elif fence==char: fence=None
        elif fence is None and re.match(r'^## [^#\n].*',line):
            matches.append((offset,line.rstrip()))
        offset+=len(line)
    if not matches or fence: return []
    titles=[title for _,title in matches]
    if len(set(titles))!=len(titles): return []
    result=[]
    for i,(start,title) in enumerate(matches):
        end=matches[i+1][0] if i+1<len(matches) else len(content)
        value=content[start:end]
        result.append({'id':f's{i+1}-{digest(value)[:12]}','title':title[3:], 'text':value,'start':start,'end':end})
    return result


def validate_scope(d, scope, frozen=()):
    if not isinstance(scope,dict) or scope.get('mode') not in ('all','selected'): fail('invalid','请选择明确的调整范围。',422)
    if scope['mode']=='all':
        if set(scope)!={'mode'}: fail('invalid','整篇调整范围格式无效。',422)
        return {'mode':'all'}
    if d['kind']=='plan':
        if set(scope)!={'mode','lessons','fields'}: fail('invalid','规划范围格式无效。',422)
        nums=scope['lessons']; fields=scope['fields']
        if not isinstance(nums,list) or not nums or any(type(n) is not int or not 1<=n<=len(d['document']['lessons']) or n in frozen for n in nums):
            fail('invalid','只能选择未发布的有效课次。',422)
        if not isinstance(fields,list) or not fields or any(not isinstance(k,str) or k not in FIELDS for k in fields):
            fail('invalid','请选择允许修改的课次字段。',422)
        return {'mode':'selected','lessons':sorted(set(nums)),'fields':sorted(set(fields))}
    if set(scope)!={'mode','sections'}: fail('invalid','课程范围格式无效。',422)
    ids=scope['sections']; allowed={s['id'] for s in sections(d['content'])}|{'sources'}
    if not sections(d['content']) or not isinstance(ids,list) or not ids or any(not isinstance(s,str) or s not in allowed for s in ids):
        fail('invalid','章节无法明确定位，请选整课或重新选择章节。',422)
    return {'mode':'selected','sections':sorted(set(ids))}


def merge(parent, scope, output):
    d=copy.deepcopy(parent)
    if scope['mode']=='all':
        if d['kind']=='plan': d['document']=output
        else:
            from copilot.generation import SEPARATOR
            parts=output.split(SEPARATOR)
            if len(parts)!=2: fail('invalid','正文与资料分隔不完整。',422)
            d['content'],d['sources']=parts
        return d
    if not isinstance(output,dict): fail('invalid','调整结果格式无效。',422)
    if d['kind']=='plan':
        if set(output)!={'updates'} or not isinstance(output['updates'],list) or not output['updates']: fail('invalid','需返回课次更新列表。',422)
        seen=set()
        for row in output['updates']:
            if not isinstance(row,dict) or set(row)!={'number','changes'}: fail('invalid','调整包含范围外字段。',422)
            n=row['number']; changes=row['changes']
            if type(n)is not int or n not in scope['lessons'] or n in seen: fail('invalid','调整了未选课次或重复课次。',422)
            if not isinstance(changes,dict) or not changes or not set(changes)<=set(scope['fields']): fail('invalid','调整包含未选字段。',422)
            seen.add(n);d['document']['lessons'][n-1].update(changes)
    else:
        if set(output)!={'sections'} or not isinstance(output['sections'],list) or not output['sections']:fail('invalid','需返回章节更新列表。',422)
        replacements={}
        for row in output['sections']:
            if not isinstance(row,dict) or set(row)!={'id','text'}: fail('invalid','章节更新格式无效。',422)
            sid=row['id']
            if not isinstance(sid,str) or sid not in scope['sections'] or sid in replacements or not isinstance(row['text'],str) or not row['text'].strip():
                fail('invalid','调整包含未选章节或重复章节。',422)
            replacements[sid]=row['text']
        for part in reversed(sections(parent['content'])):
            if part['id'] in replacements:
                value=replacements[part['id']]
                parsed=sections(value)
                if len(parsed)!=1 or parsed[0]['start']!=0 or parsed[0]['title']!=part['title']:
                    fail('invalid','局部调整不能改章节标题或插入其他章节。',422)
                d['content']=d['content'][:part['start']]+value.rstrip()+'\n\n'+d['content'][part['end']:]
        if 'sources' in replacements:d['sources']=replacements['sources']
    return d


def differences(old,new):
    result=[]
    def walk(a,b,path):
        if a==b:return
        if isinstance(a,dict) and isinstance(b,dict):
            for k in sorted(set(a)|set(b)):walk(a.get(k),b.get(k),f'{path}/{k}')
        elif isinstance(a,list) and isinstance(b,list):
            for i in range(max(len(a),len(b))):walk(a[i] if i<len(a) else None,b[i] if i<len(b) else None,f'{path}/{i+1}')
        else:result.append({'path':path,'before':a,'after':b})
    if old['kind']=='course':
        before=sections(old['content']);after=sections(new['content'])
        if before and after and [s['title'] for s in before]==[s['title'] for s in after]:
            walk(old['content'][:before[0]['start']],new['content'][:after[0]['start']],'课程/标题日期')
            for a,b in zip(before,after):walk(a['text'],b['text'],'课程/'+a['title'])
        else:walk(old['content'],new['content'],'课程/正文')
        walk(old['sources'],new['sources'],'课程/参考资料')
    else:walk(payload(old),payload(new),'规划')
    return result
