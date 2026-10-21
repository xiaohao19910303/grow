"""Run C2 acceptance with isolated localhost databases; keep durable evidence logs."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[3]
zook=Path(os.environ['TEST_ZOOK_WORKTREE']).resolve()
if 'host=127.0.0.1' not in os.environ.get('TEST_LEGACY_PG_DSN','') or not (zook/'src/modules/lighttick/actions/action-source.service.ts').is_file():
    raise SystemExit('Requires explicit localhost PostgreSQL DSN and the C2 Zook worktree.')
output=Path(os.environ.get('ACTION_SOURCE_EVIDENCE_DIR',root/'openspec/changes/action-plans-p0-clarity/evidence/source-delivery'));output.mkdir(parents=True,exist_ok=True)
suites=[('grow-source-recovery',root,[sys.executable,'-m','unittest','test_action_source_delivery','test_action_source_http','-v']),
        ('zook-source-contract-runtime',zook,['node','--experimental-transform-types','--test',
            'test/unit/lighttick-action-source-contract.test.ts','test/unit/lighttick-action-source-delivery.test.ts','test/unit/lighttick-action-p0-gates.api.test.ts'])]
results=[]
for name,cwd,args in suites:
    result=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=150)
    (output/(name+'.log')).write_text('\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines())+'\n')
    log=result.stdout+result.stderr
    count=re.search(r'Ran (\d+) tests?',log) or re.search(r'ℹ tests (\d+)',log)
    results.append({'suite':name,'exit_code':result.returncode,'tests':int(count[1]) if count else 0});print(json.dumps(results[-1]),flush=True)
(output/'results.json').write_text(json.dumps({'suites':results,'failed':[r['suite'] for r in results if r['exit_code']]},indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results))
