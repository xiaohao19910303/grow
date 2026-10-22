"""Restore a real web application to a new database and runtime, no App/Zook/AI."""
import base64
from contextlib import contextmanager
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

import db
import httpx
import psycopg2
from fastapi.testclient import TestClient
from copilot.core import digest, MODULE
from cloud_content import is_formal
from plans.github import GitHubContent
import test_standalone_backup as backup_fixture


class StandaloneRecovery(unittest.TestCase):
    def setUp(self):
        self.f=backup_fixture.StandaloneBackupTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        with psycopg2.connect(self.f.source) as c:
            cur=c.cursor();cur.execute('DROP SCHEMA tenant_fixture CASCADE');cur.execute('DROP SCHEMA public CASCADE');cur.execute('CREATE SCHEMA public')
        self.rows={}
        work=self.f.root/'work'
        for source in (Path(__file__).parent/'fixtures/renzhi').rglob('*.md'):
            relative=MODULE+'/'+source.relative_to(Path(__file__).parent/'fixtures/renzhi').as_posix();text=source.read_text()
            formal=is_formal(relative);self.rows[relative]={'hash':digest(text),'storage':'github' if formal else 'database'}
            if formal:
                path=work/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            else:self.rows[relative]['text']=text
        self.aid='article-'+('a'*20)
        article={'id':self.aid,'type':'article','title':'Recovery public article','source':'example.org','url':'https://example.org/recovery','summary':'Public recovery text','saved_at':'2026-10-22T10:00:00+08:00','read':False,'hashes':{}}
        meta='认知阅读/文章资料/'+self.aid+'/文章信息.json'
        raw=json.dumps({k:v for k,v in article.items() if k!='hashes'},ensure_ascii=False)
        article['hashes'][meta]=digest(raw);self.article=article
        self.rows[meta]={'hash':digest(raw),'storage':'database','text':raw}
        guide='认知阅读/文章资料/'+self.aid+'/中文导读.md'
        path=work/guide;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Public recovery guide')
        self.rows[guide]={'hash':digest('Public recovery guide'),'storage':'github'}
        self.f.gitcmd('-C',str(work),'add','.');self.f.gitcmd('-C',str(work),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','public course fixture')
        self.sha=self.f.gitcmd('-C',str(work),'rev-parse','HEAD').strip();self.f.gitcmd('-C',str(work),'push',str(self.f.git),'main')
        for row in self.rows.values():
            if row['storage']=='github':row['commit_sha']=self.sha
        self.env={**self.f.env,'CLOUD_DEPLOY':'1','PLAN_CONTENT_BACKEND':'github','GITHUB_CONTENT_TOKEN':'SYNTHETIC_TEST_TOKEN','APP_USERNAME':'owner','APP_PASSWORD':'SYNTHETIC-OWNER-PASSWORD-AT-LEAST-24','GROW_SCHEDULED_READING_ENABLED':'0'}
        self.date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        self.h={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}

    @contextmanager
    def boot(self,dsn,mirror,runtime):
        def transport(request):
            self.assertEqual(request.method,'GET','recovery must never write formal content')
            self.assertTrue(request.url.path.startswith('/repos/other-owner/content/'))
            path=request.url.path.split('/content/',1)[1]
            if path=='git/ref/heads/main':return httpx.Response(200,json={'object':{'sha':self.sha}})
            if path.startswith('contents/'):
                relative=path.removeprefix('contents/');ref=request.url.params.get('ref',self.sha)
                try:text=subprocess.run(['git','--git-dir',str(mirror),'show',ref+':'+relative],check=True,capture_output=True).stdout
                except Exception:return httpx.Response(404,json={})
                return httpx.Response(200,json={'type':'file','encoding':'base64','content':base64.b64encode(text).decode()})
            return httpx.Response(200,json={'default_branch':'main'})
        original=GitHubContent.request
        def request(content,*args,**kwargs):
            content.transport=httpx.MockTransport(transport);return original(content,*args,**kwargs)
        with patch.dict(os.environ,{**self.env,'DATABASE_URL':dsn,'RUNTIME_ROOT':str(runtime),'LEARN_ROOT':str(runtime/'materials')}),patch.object(db,'DATABASE_URL',dsn),patch.object(GitHubContent,'request',request):
            import tenancy
            tenancy._proxies.clear()
            spec=importlib.util.spec_from_file_location('recovered_web_'+runtime.name,Path(__file__).parents[1]/'app.py')
            dashboard=importlib.util.module_from_spec(spec);spec.loader.exec_module(dashboard)
            dashboard.PENDING_SYNC_FILE=runtime/'no-pending-sync.json'
            with TestClient(dashboard.app,base_url='https://standalone.example') as client:
                response=client.post('/api/auth/login',json={'username':'owner','password':self.env['APP_PASSWORD']},headers=self.h)
                self.assertEqual(response.status_code,200,response.text)
                yield client
            tenancy._proxies.clear()

    def post(self,client,path,body):
        response=client.post(path,json=body,headers=self.h);self.assertEqual(response.status_code,200,response.text);return response.json()

    def test_full_web_restart_backup_restore_and_tenant_boundaries(self):
        from standalone_backup import create,restore
        f=self.f
        with self.boot(f.source,f.git,f.root/'runtime-before') as client:
            with psycopg2.connect(f.source) as c:
                cur=c.cursor()
                for path,row in self.rows.items():cur.execute('INSERT INTO cloud_documents(path,data) VALUES (%s,%s) ON CONFLICT(path) DO UPDATE SET data=excluded.data',(path,json.dumps(row)))
                cur.execute('INSERT INTO reading_records(id,data) VALUES (%s,%s)',(self.aid,json.dumps(self.article)))
            lesson=client.get('/api/copilot/lessons/1');self.assertEqual(lesson.status_code,200,lesson.text)
            self.lesson=lesson.json()
            self.note=self.post_note(client)
            self.ref=self.post(client,'/api/reflections',{'record_date':self.date,'raw_text':'RECOVERY PRIVATE REFLECTION','key':'recovery-reflection-key'})
            plans=[]
            for mode in ('check','time','content'):
                values={'title':'Recovery '+mode,'period':'day','completion_mode':mode,'start_date':self.date,'end_date':self.date,'key':'recovery-create-'+mode}
                if mode=='content':values['target']={'kind':'article','course':self.aid}
                plan=self.post(client,'/api/action-plans',values)['plans'][0];plans.append(plan)
                if mode=='check':self.post(client,'/api/action-plans/'+plan['id']+'/operations',{'action':'complete','revision':plan['revision'],'key':'recovery-check-complete'})
                if mode=='time':
                    started=self.post(client,'/api/action-plans/'+plan['id']+'/operations',{'action':'start','revision':plan['revision'],'key':'recovery-time-start'})
                    self.post(client,'/api/action-plans/'+plan['id']+'/operations',{'action':'finish','revision':started['plan']['revision'],'execution_id':started['execution']['id'],'actual_minutes':20,'key':'recovery-time-finish'})
            self.post(client,'/api/reading/articles/'+self.aid+'/personal',{'data':{'read':True,'key':'recovery-article-complete','origin_action_id':plans[-1]['id']}})
            self.post(client,'/api/copilot/lessons/1/complete',{'version':self.lesson['version'],'time_spent_seconds':90,'key':'recovery-course-complete'})
            self.before=self.observe(client)
            invitation=self.post(client,'/api/account/invitations',{})['path'].split('#invite=',1)[1]
            alice=self.post(client,'/api/auth/register',{'username':'alice','password':'user-password-123','invitation':invitation})
            self.alice=alice['user']['id']
            self.assertEqual(client.get('/api/action-plans').json()['plans'],[])
            self.assertIsNone(client.get('/api/study-notes/renzhi/1').json())
            self.post(client,'/api/reflections',{'record_date':self.date,'raw_text':'ALICE PRIVATE RESTORE','key':'alice-recovery-reflection'})
        # Full process/runtime replacement before backup verifies committed PG, not memory.
        with self.boot(f.source,f.git,f.root/'runtime-restart') as client:self.assertEqual(self.observe(client),self.before)
        # Simulate branch advancement followed by process death before PG finalization.
        guide='认知阅读/文章资料/'+self.aid+'/中文导读.md'
        with psycopg2.connect(f.source) as c:
            cur=c.cursor();cur.execute('CREATE TABLE recovery_checks(id TEXT PRIMARY KEY,value TEXT)')
            cur.execute("SELECT data FROM cloud_content_settings WHERE id='binding'");binding=json.loads(cur.fetchone()[0])
            journal={'id':'restore-pending-publication','request':'fixture-request','state':'pending','files':{guide:{'formal':True,'before':digest('Public recovery guide'),'after':digest('Public recovery guide'),'text':'Public recovery guide'}},
                     'sql':[['INSERT INTO recovery_checks VALUES (?,?) ON CONFLICT(id) DO NOTHING',['restored-once','confirmed']]],'result':{},'guards':{},'adopt_existing':False,'created_at':self.date+'T10:00:00+08:00','binding':binding,'commit_sha':self.sha,'parent_sha':self.sha}
            cur.execute('INSERT INTO cloud_publications VALUES (%s,%s)',(journal['id'],json.dumps(journal)))
            interrupted={'id':'job-recovery-interrupted','type':'job','kind':'guide','state':'running','created_at':self.date+'T10:00:00+08:00','date':self.date,'raw':'PRESERVED PARTIAL OUTPUT','context':{'article_id':self.aid}}
            cur.execute('INSERT INTO reading_records VALUES (%s,%s)',(interrupted['id'],json.dumps(interrupted)))
        create(f.source,f.backup,{'other-owner/content':f.git},env=self.env,writers_stopped=True)
        restored=f.root/'restored-git';restore(f.target,f.backup,restored,env=self.env,writers_stopped=True)
        for index in range(2):
            with self.boot(f.target,restored/'content-0.git',f.root/('runtime-restored-'+str(index))) as client:
                self.assertEqual(self.observe(client),self.before)
                with psycopg2.connect(f.target) as c:
                    cur=c.cursor();cur.execute('SELECT count(*) FROM recovery_checks');self.assertEqual(cur.fetchone()[0],1)
                    cur.execute("SELECT data FROM cloud_publications WHERE id='restore-pending-publication'");self.assertEqual(json.loads(cur.fetchone()[0])['state'],'done')
                interrupted=client.get('/api/reading/jobs/job-recovery-interrupted');self.assertEqual(interrupted.status_code,200,interrupted.text)
                self.assertEqual(interrupted.json()['state'],'failed');self.assertEqual(interrupted.json()['raw'],'PRESERVED PARTIAL OUTPUT')
                self.assertNotIn('ALICE PRIVATE RESTORE',client.get('/api/search',params={'q':'PRIVATE'}).text)
                self.assertEqual(client.post('/api/auth/login',json={'username':'alice','password':'user-password-123'},headers=self.h).status_code,200)
                self.assertEqual(client.get('/api/action-plans').json()['plans'],[])
                self.assertIsNone(client.get('/api/study-notes/renzhi/1').json())

    def post_note(self,client):
        response=client.put('/api/study-notes/renzhi/1',json={'notes':'RECOVERY PRIVATE NOTE','answers':{'practice-1':'evidence'},'version':self.lesson['version'],'revision':0,'key':'recovery-note-request'},headers=self.h)
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def observe(self,client):
        result={}
        for key,path in [('actions','/api/action-plans'),('facts','/api/action-plans/records'),('note','/api/study-notes/renzhi/1'),('ref','/api/reflections/'+self.ref['id']),('record','/api/copilot/lessons/1/learning-record')]:
            response=client.get(path);self.assertEqual(response.status_code,200,response.text);result[key]=response.json()
        result['actions'].pop('server_time',None)
        lesson=client.get('/api/copilot/lessons/1');self.assertEqual(lesson.status_code,200,lesson.text)
        self.assertEqual(lesson.json()['content'],self.lesson['content']);result['content_hash']=digest(lesson.json()['content'])
        self.assertEqual({p['status'] for p in result['actions']['plans']},{'completed'})
        self.assertEqual(result['note']['notes'],'RECOVERY PRIVATE NOTE')
        search=client.get('/api/search',params={'q':'RECOVERY'});self.assertEqual(search.status_code,200,search.text)
        self.assertIn('RECOVERY PRIVATE NOTE',search.text);self.assertIn('RECOVERY PRIVATE REFLECTION',search.text)
        return result
