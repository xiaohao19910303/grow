"""A single extra lesson is provisional until curriculum and content publish together."""
import copy
from copilot.core import digest, encoded, fail, now
from .store import brief, document, plan_markdown


def extension_context(store, pid):
    p=store.plan(pid);store.check_files(p)
    lessons=store.lessons(pid);doc=copy.deepcopy(store.version(pid)['document'])
    if p['status']!='active' or not lessons or len(lessons)!=len(doc['lessons']) or any(l['learning_state']!='completed' for l in lessons):
        fail('conflict','请先学完整份正式规划，再准备额外一课。')
    previous=store.read_course(pid,max(l['lesson_no'] for l in lessons))
    entries=[{'title':'上一课教学内容（沿用资料，非新增外部来源）','content':previous['content'][:12000]}]
    if previous.get('sources'):entries.append({'title':'上一课参考资料','content':previous['sources'][:12000]})
    n=len(doc['lessons'])+1
    b=brief({**p['brief'],'pacing':'self_paced','lesson_count':n})
    doc['lessons'].append({'number':n,'topic':p['name']+'：综合迁移练习','goal':p['brief']['goal'],
        'exercise':'结合已学概念完成一个新情境中的综合练习。','assessment':'解释思路、适用边界并自查。',
        'stage':len(doc['stages']),'kind':'review','minutes':b['minutes'],'requires':[n-1]})
    document(doc,b)
    return {'plan_id':pid,'base_version':p['version'],'lesson_no':n,'date':now()[:10],
        'brief':b,'lesson':doc['lessons'][-1],'source_entries':entries,'source_hash':digest(encoded(entries)),
        'previous_topics':[l['topic'] for l in lessons[-3:]],'extension':True,'strict_sources':True,
        'extension_document':doc}


def extension_publication(store, plan, ctx):
    plan['version']+=1;plan['brief']=ctx['brief']
    base=store.base(plan['id']);version=plan['version']
    md=plan_markdown(ctx['brief'],ctx['extension_document'])
    files={base+'/学习规划.md':md,f'{base}/规划历史/v{version:03d}.md':md,
           base+'/计划信息.json':encoded({k:v for k,v in plan.items() if k!='hashes'}|{'schema_version':1})}
    sql=[('INSERT INTO learning_plan_versions VALUES (?,?,?)',[plan['id'],version,
        encoded({'brief':ctx['brief'],'document':ctx['extension_document'],'created_at':now()})])]
    return files,sql
