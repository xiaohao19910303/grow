"""The isolation runner permits temporary dir-FD writes and still blocks workspace writes."""
import os,subprocess,sys
from pathlib import Path
from unittest import TestCase

class IsolationDirfdTests(TestCase):
    def test_dirfd_writes_remain_guarded_in_child_process(self):
        script='''
import os,tempfile
from pathlib import Path
from run_isolated_checks import setup_isolation
stats,runtime,server=setup_isolation()
with tempfile.TemporaryDirectory() as tmp:
    fd=os.open(tmp,os.O_RDONLY|os.O_DIRECTORY)
    try:
        f=os.open('allowed',os.O_CREAT|os.O_WRONLY,0o600,dir_fd=fd);os.close(f)
        assert (Path(tmp)/'allowed').exists()
    finally:os.close(fd)
root=Path(__import__('run_isolated_checks').__file__).resolve().parents[3]
fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
try:
    try:os.open('.must-not-exist-dirfd',os.O_CREAT|os.O_WRONLY,0o600,dir_fd=fd)
    except (PermissionError,RuntimeError):pass
    else:raise AssertionError('workspace write allowed')
finally:os.close(fd)
assert not (root/'.must-not-exist-dirfd').exists()
assert stats['blocked_workspace_writes']==1,stats
'''
        env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+env.get('PYTHONPATH','')
        run=subprocess.run([sys.executable,'-B','-c',script],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr[-3000:])
