"""Offline CLI and shell management checks use copied entrypoints and fake credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from cryptography.fernet import Fernet

SERVER=Path(__file__).resolve().parents[1]

class RuntimeCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.server=self.root/'app/server';self.server.mkdir(parents=True)
        for filename in ('deployment.py','run_local.py'):shutil.copy2(SERVER/filename,self.server/filename)
        shutil.copy2(SERVER.parent/'manage.sh',self.server.parent/'manage.sh')
        (self.root/'materials').mkdir()
        self.env={'PATH':os.environ['PATH'],'GROW_PYTHON':sys.executable,'PYTHONDONTWRITEBYTECODE':'1',
                  'DATABASE_URL':'postgresql://PRIVATE_USER:PRIVATE_PASSWORD@127.0.0.1:1/unreachable',
                  'APP_USERNAME':'owner','APP_PASSWORD':'PRIVATE_SYNTHETIC_ADMIN_PASSWORD_123456',
                  'ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'PLAN_CONTENT_BACKEND':'github',
                  'LEARN_ROOT':str(self.root/'materials'),'RUNTIME_ROOT':str(self.root/'runtime')}
    def run_cli(self,*args,env=None):
        return subprocess.run([sys.executable,'-B',str(self.server/'deployment.py'),*args],env=self.env if env is None else env,capture_output=True,text=True,timeout=20)
    def test_offline_validates_runtime_without_reaching_unavailable_database(self):
        result=self.run_cli('check','--offline');self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout);self.assertTrue(report['ok']);self.assertFalse(report['database_checked'])
        self.assertFalse((self.server.parent/'.server.pid').exists())
    def test_default_check_still_connects_and_hides_credentials(self):
        result=self.run_cli('check');self.assertEqual(result.returncode,2)
        self.assertIn('DATABASE_URL',result.stderr);self.assertNotIn('PRIVATE',result.stderr+result.stdout)
    def test_serve_cannot_bypass_database_checks(self):
        result=self.run_cli('serve','--offline');self.assertEqual(result.returncode,2)
        self.assertIn('--offline 仅适用于 check',result.stderr);self.assertNotIn('PRIVATE',result.stderr+result.stdout)
    def test_offline_requires_real_config_fields_and_never_mutates_source_config(self):
        path=self.server/'.env';path.write_text('APP_USERNAME=owner\n');before=path.read_bytes()
        env={k:v for k,v in self.env.items() if k not in ('APP_PASSWORD','ACCOUNT_ENCRYPTION_KEY')}
        result=self.run_cli('check','--offline',env=env);self.assertEqual(result.returncode,2)
        self.assertIn('APP_PASSWORD',result.stderr);self.assertIn('ACCOUNT_ENCRYPTION_KEY',result.stderr)
        self.assertEqual(path.read_bytes(),before);self.assertNotIn('PRIVATE',result.stderr+result.stdout)
    def test_offline_still_checks_runtime_and_material_paths(self):
        for values,field in [({'LEARN_ROOT':str(self.root/'missing')},'LEARN_ROOT'),({'RUNTIME_ROOT':str(self.root/'not-a-dir')},'RUNTIME_ROOT')]:
            (self.root/'not-a-dir').write_text('fixture')
            result=self.run_cli('check','--offline',env={**self.env,**values})
            self.assertEqual(result.returncode,2);self.assertIn(field,result.stderr)
    def test_manage_check_forwards_offline_without_starting_server(self):
        result=subprocess.run(['bash',str(self.server.parent/'manage.sh'),'check','--offline'],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertFalse(json.loads(result.stdout.splitlines()[-1])['database_checked'])
        self.assertFalse((self.server.parent/'.server.pid').exists());self.assertFalse((self.server.parent/'.server.log').exists())
