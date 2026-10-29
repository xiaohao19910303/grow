"""Read authoritative course content separately from explicitly selected private records."""
import json
import db
from copilot.core import digest, encoded, fail

NAMES={'renzhi':'认知与通识','yingyu':'英文阅读','biaoda':'结构化表达'}

class CourseSources:
    def __init__(self,plans,materials,copilot):self.plans,self.materials,self.copilot=plans,materials,copilot

    def read(self,key,content=False):
        if key.startswith('plan:'):
            pid=key[5:];p=self.plans.plan(pid);doc=self.plans.version(pid)['document']
            lessons=self.plans.lessons(pid);name=p['name'];status=p['status'];conditions=p['brief']
            version={'version':p['version'],'hashes':p['hashes'],'document':doc}
        elif key in NAMES:
            pid=None;doc=None;name=NAMES[key];status='active'
            if key=='renzhi':
                scan=self.copilot.scan();lessons=scan['lessons'];version={'plan':self.copilot.plan()['hash']}
            else:lessons=self.materials.lessons(key);version={}
            conditions={'goal':'衔接已学内容，继续理解与应用。','minutes':35 if key=='yingyu' else 15,'level':'已学当前课程基础'}
        else:fail('not_found','课程不存在。',404)
        lessons=sorted(lessons,key=lambda l:l['lesson_no'])
        snapshot=digest(encoded({'course_key':key,'status':status,'version':version,
            'lessons':[{k:l.get(k) for k in ('lesson_no','filename','version','learning_state')} for l in lessons]}))
        pending=next((l for l in lessons if l['learning_state']!='completed'),None)
        total=len(doc['lessons']) if doc else None
        result={'course_key':key,'name':name,'status':status,'snapshot':snapshot,'brief':conditions,
            'curriculum':doc,'topics':[{'lesson_no':l['lesson_no'],'topic':l['topic']} for l in lessons[-24:]],
            'next_lesson':pending,'total':total,'published':len(lessons),
            'completed':sum(l['learning_state']=='completed' for l in lessons),
            'can_extend':bool(pid and total and total==len(lessons) and not pending),
            'lessons':lessons,'content':'','sources':''}
        if content and lessons:
            last=lessons[-1]
            data=self.plans.read_course(pid,last['lesson_no']) if pid else self.copilot.lesson(last['lesson_no']) if key=='renzhi' else self.materials.lesson(key,last['filename'])
            result.update(content=data.get('content','')[:12000],sources=data.get('sources','')[:12000])
        return result

    def teaching(self,key):
        source=self.read(key,True)
        return {k:source[k] for k in ('course_key','name','brief','curriculum','topics','content','sources')}

    def private_records(self,key):
        source=self.read(key);items=[]
        def add(ref,label,data,table,keys,fields):
            if any(data.values()):
                from history_sources import record_source
                reference=record_source(c,table,keys,label,data,fields=fields)
                items.append({'ref':ref,'label':label,'data':data,'version':digest(encoded(data)),'source':reference})
        kind='plan' if key.startswith('plan:') else key
        with db.connect() as c:
            if c.execute("SELECT to_regclass('course_study_notes')").fetchone()[0]:
                rows=c.execute('SELECT course_id,data FROM course_study_notes WHERE kind=? ORDER BY updated_at DESC',(kind,)).fetchall()
                allowed={str(l['lesson_no']) if kind=='renzhi' else key[5:]+'/'+str(l['lesson_no']) if kind=='plan' else l['filename']:l for l in source['lessons']}
                for row in rows:
                    if row[0] in allowed:
                        doc=json.loads(row[1]);add('note:'+digest(kind+':'+row[0]),f"第{allowed[row[0]]['lesson_no']}课笔记与练习",{k:doc.get(k) for k in ('notes','answers')},'course_study_notes',(kind,row[0]),['notes','answers'])
            if kind=='plan':
                for row in c.execute('SELECT lesson_no,data FROM learning_feedback WHERE plan_id=?',(key[5:],)):
                    d=json.loads(row[1]);add('feedback:'+str(row[0]),f'第{row[0]}课学习反馈',{'comment':d.get('comment','')},'learning_feedback',(key[5:],row[0]),['comment'])
            elif kind=='renzhi':
                allowed={l['lesson_no'] for l in source['lessons']}
                for row in c.execute("SELECT lesson_no,summary_text,review_answers FROM copilot_learning_records WHERE module_id='renzhi' AND round_id=1 ORDER BY lesson_no DESC"):
                    if row[0] in allowed:add('feedback:'+str(row[0]),f'第{row[0]}课完成记录',{'summary_text':row[1],'review_answers':json.loads(row[2]) if row[2] else {}},'copilot_learning_records',('renzhi',1,row[0]),['summary_text','review_answers'])
            else:
                for row in c.execute('SELECT lesson_no,summary_text,filename FROM study_learning_records WHERE module_id=?',(kind,)):
                    add('feedback:'+str(row[0]),f'第{row[0]}课完成收获',{'summary_text':row[1]},'study_learning_records',(kind,row[2]),['summary_text'])
        return items[:100]

    def selected(self,key,refs,versions=None):
        available={x['ref']:x for x in self.private_records(key)}
        if any(ref not in available for ref in refs):fail('conflict','选择的私人记录已变化，请重新核对。')
        if versions is not None and (not isinstance(versions,dict) or any(versions.get(ref)!=available[ref]['version'] for ref in refs)):
            fail('conflict','选定的私人记录已更新，请重新读取并核对发送范围。')
        result=[available[ref] for ref in refs]
        if len(encoded([{k:x[k] for k in ('ref','label','data')} for x in result]))>60000:fail('invalid','选中的私人记录过多，请减少后重试。',422)
        return result
