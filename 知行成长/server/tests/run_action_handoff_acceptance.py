"""Reproducible C3 acceptance; only disposable localhost schemas and closed gates."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parents[3]
zook=Path(os.environ['TEST_ZOOK_WORKTREE']).resolve()
if 'host=127.0.0.1' not in os.environ.get('TEST_LEGACY_PG_DSN','') or not (zook/'src/modules/lighttick/actions/action-handoff.service.ts').is_file():
    raise SystemExit('Requires explicit localhost PostgreSQL DSN and C3 Zook worktree.')
output=Path(os.environ.get('ACTION_HANDOFF_EVIDENCE_DIR',root/'openspec/changes/action-plans-p0-clarity/evidence/handoff-cutover'))
output.mkdir(parents=True,exist_ok=True)
suites=[('grow-cutover-recovery',root,[sys.executable,'-m','unittest','test_action_handoff_cutover','-v']),
        ('grow-snapshot-and-routing',root,[sys.executable,'-m','unittest','test_action_handoff','-v']),
        ('zook-contracts-and-gates',zook,['node','--experimental-transform-types','--test',
            'test/unit/lighttick-action-handoff-v2.test.ts','test/unit/lighttick-action-handoff-contract.test.ts',
            'test/unit/lighttick-action-p0-contract.test.ts','test/unit/lighttick-action-source-contract.test.ts',
            'test/unit/lighttick-action-p0-gates.api.test.ts','test/unit/public-contract-generation.test.ts'])]
results=[]
for name,cwd,args in suites:
    result=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=240)
    log='\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines()).rstrip()+'\n'
    (output/(name+'.log')).write_text(log)
    count=re.search(r'Ran (\d+) tests?',log) or re.search(r'ℹ tests (\d+)',log)
    skip=re.search(r'skipped=(\d+)',log) or re.search(r'ℹ skipped (\d+)',log)
    results.append(dict(suite=name,exit_code=result.returncode,tests=int(count[1]) if count else 0,skipped=int(skip[1]) if skip else 0))
    print(json.dumps(results[-1]),flush=True)
(output/'results.json').write_text(json.dumps(dict(suites=results,failed=[r['suite'] for r in results if r['exit_code']]),indent=2)+'\n')
raise SystemExit(any(r['exit_code'] or r['skipped'] or not r['tests'] for r in results))
