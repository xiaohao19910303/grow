"""Run domain regressions in fresh interpreters; emit reviewable JSON and logs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SUITES = ('test_action_p0', 'test_action_p0_sources', 'test_action_p0_closeout', 'test_action_p0_closeout_sources',
          'test_action_p0_browser', 'test_action_plans', 'test_action_reviews',
          'test_daily_arrangements', 'test_arrangement_sources', 'test_github_plans',
          'test_study_notes', 'test_study_materials', 'test_legacy_cloud_schema', 'test_legacy_cloud_content',
          'test_legacy_cloud_api', 'test_plan_read_errors')


def main():
    if 'host=127.0.0.1' not in os.environ.get('TEST_LEGACY_PG_DSN', ''):
        raise SystemExit('Set TEST_LEGACY_PG_DSN to a disposable localhost PostgreSQL database.')
    root=Path(__file__).resolve().parents[3]
    output=root/'openspec/changes/action-plans-p0-clarity/evidence'
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for suite in SUITES:
        result=subprocess.run([sys.executable,'-m','unittest',suite,'-v'],capture_output=True,text=True,timeout=120)
        log='\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines())+'\n'
        (output/(suite+'.log')).write_text(log)
        count=re.search(r'Ran (\d+) tests?',log)
        skipped=re.search(r'OK \(skipped=(\d+)\)',log)
        item=dict(suite=suite,exit_code=result.returncode,tests=int(count[1]) if count else 0,
                  skipped=int(skipped[1]) if skipped else 0)
        results.append(item);print(json.dumps(item),flush=True)
    summary=dict(results=results,tests=sum(r['tests'] for r in results),skipped=sum(r['skipped'] for r in results),
                 failed_suites=[r['suite'] for r in results if r['exit_code']])
    (output/'regression-results.json').write_text(json.dumps(summary,indent=2))
    raise SystemExit(bool(summary['failed_suites']))


if __name__=='__main__':main()
