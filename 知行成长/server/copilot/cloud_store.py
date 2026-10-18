"""Legacy course API backed by immutable GitHub documents and PostgreSQL records."""
import json
import copy
import re
from contextlib import contextmanager

from cloud_content import ContentPath, Documents, enabled
from legacy_schema import migrate
from .core import Store, MODULE, digest, encoded, fail, now, completion_label


class CloudStore(Store):
    remote=True

    def __init__(self,root,db,content=None):
        super().__init__(root,db)
        self.documents=Documents(self,content)
        self.module=ContentPath(self.documents,MODULE)

    def initialize(self):
        migrate()
        self.documents.initialize()
        with self.lock():
            if self.documents.metadata(MODULE+'/学习记录.md') is None:
                self.documents.publish('seed-course-record',{'seed':'course-record'},{MODULE+'/学习记录.md':'# 学习记录\n\n| 课次 | 日期 | 课程 | 资料 | 状态 |\n|---|---|---|---|---|\n'})
            with self.conn() as c:
                c.execute("UPDATE copilot_drafts SET status='failed' WHERE status='generating'")
                c.execute("UPDATE copilot_generation_attempts SET status='failed' WHERE status='generating'")

    def workspace(self):pass

    @contextmanager
    def lock(self):
        with self.documents.lock():yield

    def generation_gate(self):return self.documents.generation_gate()

    def path(self,relative):
        if not isinstance(relative,str) or relative.startswith('/') or '..' in relative.split('/'):
            fail('invalid','课程路径无效。',422)
        return ContentPath(self.documents,MODULE+'/'+relative)

    def plan(self):
        if not self.path('学习规划.md').exists() and not self.path('课程主题规划.md').exists():
            return {'hash':digest(''),'path':None,'items':[]}
        return super().plan()

    def coordinated(self):return True
    def require_writer(self):pass
    def writer_session(self,confirmed):return {'coordinated':True,'storage':'database'}

    def _scan(self):
        revision=digest(encoded({path:item['hash'] for path,item in self.documents.rows('cloud_documents') if path.startswith(MODULE+'/')}))
        cached=self.meta('cloud-scan')
        if cached and cached['revision']==revision:
            result=copy.deepcopy(cached['result'])
        else:
            result=super()._scan()
            self.set_meta('cloud-scan',{'revision':revision,'result':result})
        with self.conn() as c:
            states={r[0]:json.loads(r[1]) for r in c.execute("SELECT key,value FROM copilot_meta WHERE key LIKE 'learning-state:%'")}
            records={r['lesson_no']:dict(r) for r in c.execute("SELECT lesson_no,completed_at,time_spent_seconds FROM copilot_learning_records WHERE module_id='renzhi' AND round_id=1")}
            pending=[r[0] for r in c.execute("SELECT id FROM copilot_operations WHERE status!='done'")]
        result['blockers']=[b for b in result['blockers'] if b['code']!='save_pending_recovery']
        result['blockers'].extend({'code':'save_pending_recovery','message':'保存操作需要恢复','operation_id':key} for key in pending)
        for lesson in result['lessons']:
            state=states.get('learning-state:'+str(lesson['lesson_no']))
            record=records.get(lesson['lesson_no'])
            if record:
                lesson.update(learning_state='completed',learning_label=completion_label(record),**{k:v for k,v in record.items() if k!='lesson_no'})
            elif state:
                lesson.update(learning_state=state['state'],learning_label='本人确认完成' if state['state']=='completed' else '待本人反馈')
            lesson['version']=digest(lesson['content_hash']+lesson['source_hash']+encoded(state))
        result['today_lessons']=[x for x in result['lessons'] if x['date']==now()[:10]]
        result['completed_count']=sum(x['learning_state']=='completed' for x in result['lessons'])
        result['pending_learning_lessons']=[x for x in result['lessons'] if x['learning_state']!='completed']
        return result

    def lesson(self,number):
        lesson=super().lesson(number)
        item=self.documents.metadata(MODULE+'/'+lesson['path'])
        if item and item['storage']=='github':
            lesson.update(commit_sha=item['commit_sha'],github_url=self.documents.content.url(MODULE+'/'+lesson['path'],item['commit_sha']))
        return lesson

    def prepare(self,key,request,files,draft_id=None):
        op_id='cloud-'+digest(key)[:32]
        with self.conn() as c:
            old=c.execute('SELECT * FROM copilot_operations WHERE request_key=?',(key,)).fetchone()
            if old:
                if old['request_hash']!=digest(encoded(request)):fail('conflict','请求标识已用于其他内容。')
                return self._resume(old['id'])
            data={'files':files,'draft_id':draft_id}
            c.execute('INSERT INTO copilot_operations VALUES (?,?,?,?,?,?)',(op_id,key,digest(encoded(request)),'prepared',encoded(data),now()))
        return self._resume(op_id)

    def _resume(self,op_id):
        row=self.operation(op_id)
        if row['status']=='done':
            journal=self.documents.get('cloud_publications',op_id)
            return journal['result'] if journal else {'operation_id':op_id,'status':'done'}
        data=json.loads(row['data'])
        files={MODULE+'/'+item['path']:item['content'] for item in data.get('files',[])}
        expected={MODULE+'/'+item['path']:item['old_hash'] for item in data.get('files',[])}
        for path,old in expected.items():
            if self.documents.hash(path) not in (old,digest(files[path])):fail('conflict','课程资料已变化，原文保留。')
        sql=[("UPDATE copilot_operations SET status='done' WHERE id=?",[op_id])]
        if data.get('draft_id'):sql.append(("UPDATE copilot_drafts SET status='published' WHERE id=?",[data['draft_id']]))
        guards={path:self.documents.hash(path) for path in self.documents.names(MODULE+'/')
                if path.endswith(('学习规划.md','课程主题规划.md')) or '/备课资料/' in path and path.endswith('.md')}
        return self.documents.publish(op_id,{'operation':op_id},files,sql,{'operation_id':op_id,'status':'done'},guards=guards)

    def replay(self,key,request):
        with self.conn() as c:old=c.execute('SELECT * FROM copilot_operations WHERE request_key=?',(key,)).fetchone()
        if old:
            if old['request_hash']!=digest(encoded(request)):fail('conflict','相同请求标识不能用于不同内容。')
            return self._resume(old['id'])

    def publish(self,draft_id,version,key):
        request={'draft_id':draft_id,'version':version}
        with self.lock():
            previous=self.replay(key,request)
            if previous:return previous
            d=self.draft(draft_id)
            if d['version']!=version or d['status']!='ready' or self.validate_draft(d):fail('conflict','草稿版本已改变或尚未通过校验。')
            state,plan,sources,blockers=self.readiness()
            if blockers:fail(blockers[0]['code'],blockers[0]['message'])
            if state['next_generation_lesson']!=d['lesson_no'] or plan['hash']!=d['plan_snapshot']['hash'] or sources['hash']!=d['source_snapshot']['hash']:
                fail('conflict','课次、规划或备课资料已变化，请重新生成。')
            n=d['lesson_no'];date=now()[:10]
            title=re.sub(r'[\\/:*?"<>|\x00-\x1f\[\]()]','',plan['topic']).strip()[:70] or f'第{n:03d}课'
            course=f'每日课程/{date}-第{n:03d}课-{title}.md';source=f'参考资料/第{n:03d}课-参考资料.md'
            if self.file_hash(course) is not None or self.file_hash(source) is not None:fail('conflict','正式课程已存在，不能覆盖。')
            content=re.sub(r'(日期[：:]\s*)\d{4}-\d{2}-\d{2}',r'\g<1>'+date,d['content'],count=1)+f'\n\n资料：[第{n:03d}课参考资料](../{source})\n'
            source_text=f'# 第{n:03d}课参考资料\n\n对应课程：[{title}](../{course})\n\n'+d['sources']
            record=self.path('学习记录.md').read_text();rows=self.record_rows(record)
            if any(number==n for _,number,_ in rows):fail('conflict','学习目录中已存在该课。')
            lines=record.splitlines(keepends=True)
            position=max((i for i,_,_ in rows),default=-1)+1 if rows else next((i+1 for i,line in enumerate(lines) if line.startswith('|---')),-1)
            if position<0:fail('conflict','学习目录格式无法识别。')
            lines.insert(position,f'| {n:03d} | {date} | [{title}]({course}) | [参考资料]({source}) | 待本人记录 |\n')
            # Public catalog never includes personal completion labels or notes.
            catalog='# 课程目录\n\n'+'\n'.join(f'- [{x["topic"]}]({x["path"]}) · [参考资料]({x["source_path"]})' for x in state['lessons'])+f'\n- [{title}]({course}) · [参考资料]({source})\n'
            return self.prepare(key,request,[{'path':course,'old_hash':None,'content':content},
                {'path':source,'old_hash':None,'content':source_text},
                {'path':'课程目录.md','old_hash':self.file_hash('课程目录.md'),'content':catalog},
                {'path':'学习记录.md','old_hash':digest(record),'content':''.join(lines)}],draft_id)

    def _complete(self,number,state,version,key,completion_type='manual',answers=None,summary=None,time_spent=0):
        request={'lesson_no':number,'state':state,'version':version,'type':completion_type,'answers':answers,'summary':summary,'seconds':time_spent}
        with self.lock():
            old=self.documents.get('cloud_publications','learning:'+key)
            if old:
                return self.documents.publish('learning:'+key,request,{})
            lesson=next((x for x in self._scan()['lessons'] if x['lesson_no']==number),None)
            if not lesson:fail('not_found','未找到课程。',404)
            if not lesson['complete'] or lesson['version']!=version:fail('conflict','课程版本已更新，请刷新后再保存反馈。')
            sql=[]
            if state=='completed':
                sql.append(('''INSERT INTO copilot_learning_records(module_id,round_id,lesson_no,completion_type,review_answers,summary_text,time_spent_seconds,completed_at,idempotency_key)
                VALUES ('renzhi',1,?,?,?,?,?,?,?) ON CONFLICT(module_id,round_id,lesson_no) DO UPDATE SET completion_type=excluded.completion_type,review_answers=excluded.review_answers,summary_text=excluded.summary_text,time_spent_seconds=excluded.time_spent_seconds,completed_at=excluded.completed_at,idempotency_key=excluded.idempotency_key''',
                [number,completion_type,encoded(answers) if answers is not None else None,summary,time_spent,now(),key]))
            else:sql.append(("DELETE FROM copilot_learning_records WHERE module_id='renzhi' AND round_id=1 AND lesson_no=?",[number]))
            sql.append(('INSERT INTO copilot_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        ['learning-state:'+str(number),encoded({'state':state,'updated_at':now(),'key':key})]))
            return self.documents.publish('learning:'+key,request,{},sql,{'status':'done','operation_id':'learning:'+key})

    def learning(self,number,state,version,key):return self._complete(number,state,version,key)
    def submit_review(self,number,answers,time_spent,version,key):return self._complete(number,'completed',version,key,'review',answers=answers,time_spent=time_spent)
    def submit_summary(self,number,summary,time_spent,version,key):return self._complete(number,'completed',version,key,'summary',summary=summary,time_spent=time_spent)
    def quick_complete(self,number,time_spent,version,key):return self._complete(number,'completed',version,key,'quick',time_spent=time_spent)


def make_store(root,db):return CloudStore(root,db) if enabled() else Store(root,db)
