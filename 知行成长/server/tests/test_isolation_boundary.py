"""Exercise the safety harness in child processes so expected denials stay isolated."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

SERVER=Path(__file__).resolve().parents[1]


class IsolationBoundaryTests(unittest.TestCase):
    def test_child_processes_can_import_server_and_write_only_temporary_evidence(self):
        source=f'''
import sys,os,json,subprocess
from pathlib import Path
sys.path.insert(0,{str(SERVER/'tests')!r})
from run_isolated_checks import setup_isolation
stats,runtime,server=setup_isolation()
try:
 evidence=Path(os.environ['TEST_ARTIFACTS_DIR'])
 assert evidence.is_relative_to(Path(runtime.name))
 evidence.mkdir(parents=True,exist_ok=True)
 (evidence/'probe.txt').write_text('synthetic evidence')
 child=subprocess.run([sys.executable,'-B','-c','import copilot.api; print("imported")'],cwd=runtime.name,capture_output=True,text=True)
 assert child.returncode==0,child.stderr
 print(json.dumps(stats))
finally:runtime.cleanup()
'''
        result=subprocess.run([sys.executable,'-B','-c',source],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(json.loads(result.stdout)[key] for key in (
            'blocked_workspace_writes','blocked_real_database_access','blocked_network_access')))

    def probe(self,action,field):
        source=f'''
import sys,json
sys.path.insert(0,{str(SERVER/'tests')!r})
from run_isolated_checks import setup_isolation
stats,runtime,server=setup_isolation()
try:
 try:
  {action}
 except RuntimeError:pass
 else:raise AssertionError('unsafe action was allowed')
 print(json.dumps(stats))
finally:runtime.cleanup()
'''
        result=subprocess.run([sys.executable,'-B','-c',source],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        stats=json.loads(result.stdout);self.assertEqual(stats[field],1)

    def test_rejects_remote_postgresql_before_connecting(self):
        self.probe("__import__('psycopg2').connect('host=203.0.113.1 dbname=not_real')",'blocked_real_database_access')

    def test_rejects_workspace_sqlite_before_opening(self):
        self.probe("__import__('sqlite3').connect(server/'data.db')",'blocked_real_database_access')

    def test_rejects_workspace_writes_before_creating_files(self):
        self.probe("(server/'_regression_probe.tmp').write_text('never write')",'blocked_workspace_writes')
        self.assertFalse((SERVER/'_regression_probe.tmp').exists())

    def test_rejects_external_http_sockets(self):
        self.probe("__import__('socket').socket().connect(('203.0.113.1',443))",'blocked_network_access')

    def test_full_run_cannot_succeed_by_skipping_postgresql(self):
        env={k:v for k,v in os.environ.items() if not k.startswith('TEST_')}
        result=subprocess.run([sys.executable,'-B',str(SERVER/'tests/run_isolated_checks.py'),'--full'],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('requires TEST_POSTGRES_DSN',result.stderr)

    def test_full_run_cannot_select_only_part_of_the_suite(self):
        result=subprocess.run([sys.executable,'-B',str(SERVER/'tests/run_isolated_checks.py'),'--full','--pattern','none.py'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('cannot restrict test patterns',result.stderr)

    def test_full_run_requires_explicit_zook_contract_checkout(self):
        env={k:v for k,v in os.environ.items() if k!='TEST_ZOOK_WORKTREE'}
        env['TEST_POSTGRES_DSN']='host=127.0.0.1 port=1 dbname=not_connected'
        result=subprocess.run([sys.executable,'-B',str(SERVER/'tests/run_isolated_checks.py'),'--full'],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('requires TEST_ZOOK_WORKTREE',result.stderr)
