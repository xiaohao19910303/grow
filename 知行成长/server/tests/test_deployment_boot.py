"""The documented command starts a new installation and survives a process restart."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from urllib.parse import quote

import httpx
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn
from cryptography.fernet import Fernet

SERVER=Path(__file__).resolve().parents[1]

class DeploymentBoot(unittest.TestCase):
    def test_documented_entrypoint_no_github_ai_app_or_zook_then_restart(self):
        admin=os.environ['TEST_POSTGRES_DSN'];settings=parse_dsn(admin);assert settings['host']=='127.0.0.1'
        name='web_boot_'+uuid.uuid4().hex
        c=psycopg2.connect(admin);c.autocommit=True;c.cursor().execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));c.close()
        def drop():
            c=psycopg2.connect(admin);c.autocommit=True;c.cursor().execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)));c.close()
        self.addCleanup(drop)
        with tempfile.TemporaryDirectory(prefix='grow-entrypoint-') as temp:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url='postgresql://'+quote(settings['user'])+'@127.0.0.1:'+settings.get('port','5432')+'/'+name
            env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1','DATABASE_URL':url,
                 'ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'APP_PASSWORD':'SYNTHETIC-BOOT-PASSWORD-OVER-24-CHARS','APP_USERNAME':'owner',
                 'PLAN_CONTENT_BACKEND':'github','CLOUD_DEPLOY':'0','WEB_CONCURRENCY':'1','GROW_SCHEDULED_READING_ENABLED':'0',
                 'RUNTIME_ROOT':temp+'/runtime','LEARN_ROOT':temp+'/materials'}
            from prepare_materials import prepare
            prepare(SERVER.parent/'学习资料',env['LEARN_ROOT'])
            self.assertFalse((Path(env['LEARN_ROOT'])/'英文阅读/学习记录.md').exists())
            checked=subprocess.run([sys.executable,'-B',str(SERVER/'deployment.py'),'check'],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(checked.returncode,0,checked.stderr);self.assertIn('github_content_unconfigured',checked.stdout)
            broken=subprocess.run([sys.executable,'-B',str(SERVER/'deployment.py'),'check'],env={**env,'DATABASE_URL':'postgresql://SENSITIVE_USER:SENSITIVE_PASSWORD@127.0.0.1:1/unreachable'},capture_output=True,text=True,timeout=15)
            self.assertEqual(broken.returncode,2);self.assertIn('DATABASE_URL',broken.stderr);self.assertNotIn('SENSITIVE',broken.stderr)
            for index in range(2):
                with (Path(temp)/('server-'+str(index)+'.log')).open('w') as log:
                    process=subprocess.Popen([sys.executable,'-B',str(SERVER/'deployment.py'),'serve','--port',str(port)],env=env,stdout=log,stderr=subprocess.STDOUT,cwd=SERVER)
                    try:
                        with httpx.Client(base_url='http://127.0.0.1:'+str(port)) as client:
                            for _ in range(150):
                                if process.poll() is not None:self.fail('Documented server exited; inspect synthetic boot fixture')
                                try:
                                    if client.get('/api/health').status_code==200:break
                                except httpx.TransportError:pass
                                time.sleep(.1)
                            else:self.fail('Server did not become alive')
                            h={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
                            login=client.post('/api/auth/login',json={'username':'owner','password':env['APP_PASSWORD']},headers=h)
                            self.assertEqual(login.status_code,200,login.text)
                            modules=client.get('/api/study-materials');self.assertEqual(modules.status_code,200,modules.text)
                            english=next(module for module in modules.json()['modules'] if module['id']=='yingyu')
                            self.assertTrue(english['lessons']);self.assertTrue(all(lesson['learning_state']=='unknown' for lesson in english['lessons']))
                            if index==0:
                                state=client.get('/api/data').json();state['todos']=[{'id':'boot-todo','date':'2026-10-22','title':'Synthetic restart proof','done':0}]
                                saved=client.put('/api/data',json=state,headers={**h,'X-Legacy-State-Protocol':'1'});self.assertEqual(saved.status_code,200,saved.text)
                                action=client.post('/api/action-plans',json={'title':'Boot without optional services','period':'day','completion_mode':'check','start_date':None,'end_date':None,'key':'boot-create-check'},headers=h)
                                self.assertEqual(action.status_code,200,action.text)
                                note=client.put('/api/study-notes/renzhi/1',json={'notes':'Synthetic boot note','answers':{},'version':'a'*64,'revision':0,'key':'boot-note-request'},headers=h)
                                self.assertEqual(note.status_code,200,note.text)
                            else:
                                self.assertEqual(client.get('/api/data').json()['todos'][0]['id'],'boot-todo')
                                self.assertEqual(client.get('/api/action-plans').json()['plans'][0]['title'],'Boot without optional services')
                                self.assertEqual(client.get('/api/study-notes/renzhi/1').json()['notes'],'Synthetic boot note')
                            response=client.get('/api/reading/scheduled-run');self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['state'],'disabled')
                    finally:
                        process.terminate()
                        try:process.wait(timeout=15)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
