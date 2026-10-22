"""Standalone web profile: all discovered web tests, isolated by module; no Zook required."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

SERVER = Path(__file__).resolve().parents[1]
TESTS = SERVER / 'tests'
PYTHON_TIMEOUTS = {'test_accounts.py':600}
PYTHON_GROUPS = {'test_accounts.py': ('PasswordTests','AccountIntegrationTests','AccountBrowserTests')}
CONNECTION_TESTS = {'test_action_source_http.py': 'Requires the separate Zook HTTP/PG fixture; deferred connection profile.'}


def inventory():
    python = sorted(p.relative_to(TESTS).as_posix() for p in TESTS.rglob('test_*.py'))
    return {'profile': 'standalone-web', 'python': [p for p in python if p not in CONNECTION_TESTS],
            'python_groups':PYTHON_GROUPS, 'python_timeout_seconds':PYTHON_TIMEOUTS, 'javascript': sorted(p.name for p in TESTS.glob('test_*.cjs')),
            'deferred_connection': [{'file': p, 'reason': why} for p, why in CONNECTION_TESTS.items() if p in python]}


def check_group_coverage(results):
    if not results or any(not isinstance(r.get('node_ids'),list) or not isinstance(r.get('all_node_ids'),list) for r in results):return False
    expected=set(results[0]['all_node_ids'])
    if not expected or any(set(r['all_node_ids'])!=expected for r in results):return False
    actual=[node for r in results for node in r['node_ids']]
    return len(actual)==len(set(actual)) and set(actual)==expected


def child(filename, case_group=None):
    sys.path.insert(0, str(TESTS))
    from run_isolated_checks import setup_isolation
    stats, runtime, _ = setup_isolation()
    try:
        import pytest
        class Counts:
            collected = 0
            failed = 0
            skipped = 0
            all_node_ids = None
            node_ids = None
            def pytest_collection_modifyitems(self, config, items):
                if case_group is None:return
                self.all_node_ids=[item.nodeid for item in items]
                classes={item.getparent(pytest.Class).name if item.getparent(pytest.Class) else None for item in items}
                if not classes <= set(PYTHON_GROUPS[filename]):
                    raise pytest.UsageError('Grouped file collection changed; update the explicit groups before running.')
                selected=[item for item in items if item.getparent(pytest.Class).name==case_group]
                self.node_ids=[item.nodeid for item in selected]
                config.hook.pytest_deselected(items=[item for item in items if item not in selected])
                items[:]=selected
            def pytest_collection_finish(self, session): self.collected = len(session.items)
            def pytest_runtest_logreport(self, report):
                if case_group and report.when=='call':print('WEB_CASE_RESULT '+json.dumps({'node_id':report.nodeid,'outcome':report.outcome,'seconds':round(report.duration,3)}),flush=True)
                if report.failed: self.failed += 1
                if report.skipped: self.skipped += 1
        counts = Counts()
        code = pytest.main(['-q', '-p', 'no:cacheprovider', '--import-mode=importlib', str(TESTS / filename)], plugins=[counts])
        summary = {'tests': counts.collected, 'failed': counts.failed, 'skipped': counts.skipped,
                   'exit_code': int(code), 'isolation': stats}
        if case_group is not None:summary.update(node_ids=counts.node_ids,all_node_ids=counts.all_node_ids)
        print('WEB_MODULE_RESULT ' + json.dumps(summary), flush=True)
        return int(bool(code or counts.failed or counts.skipped or not counts.collected or any(v for k,v in stats.items() if k.startswith('blocked_'))))
    finally:
        runtime.cleanup()


def execute(command, env, timeout):
    try:return subprocess.run(command,cwd=SERVER,env=env,capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def decoded(value):return value.decode(errors='replace') if isinstance(value,bytes) else (value or '')
        return subprocess.CompletedProcess(command,124,decoded(error.stdout),decoded(error.stderr)+'\nTEST MODULE TIMED OUT\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--match', help='Diagnostic regex subset; never labelled full profile.')
    parser.add_argument('--child', help=argparse.SUPPRESS)
    parser.add_argument('--case-group', help=argparse.SUPPRESS)
    parser.add_argument('--output', default='/tmp/grow-web-regression')
    args = parser.parse_args()
    plan = inventory()
    if args.list:
        print(json.dumps(plan, indent=2)); return 0
    if args.child:
        if args.child not in plan['python']: parser.error('Unknown web test module')
        if args.case_group and args.case_group not in PYTHON_GROUPS.get(args.child,()):parser.error('Unknown case group')
        return child(args.child,args.case_group)
    dsn = os.getenv('TEST_POSTGRES_DSN', '')
    if 'host=127.0.0.1' not in dsn: parser.error('Requires explicit TEST_POSTGRES_DSN for disposable localhost PostgreSQL')
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if k not in ('DATABASE_URL','GROW_ACTION_BRIDGE_SECRET','LIGHTTICK_BRIDGE_URL')}
    env.update(TEST_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTHONPATH=os.pathsep.join((str(SERVER),str(TESTS))), ACTION_P0_EVIDENCE_DIR=str(output/'screenshots'), RUN_GITHUB_BROWSER='1', RUN_LEGACY_BROWSER='1', RUN_ACCOUNTS_BROWSER='1')
    for name in ('TEST_LEGACY_PG_DSN','TEST_GITHUB_PG_DSN','TEST_ACCOUNTS_PG_DSN'): env[name] = dsn
    if not args.match:env['PYTEST_ADDOPTS']='--durations=5'
    results = []
    for name in plan['python']:
        if args.match and not re.search(args.match, name): continue
        grouped=[]
        for group in PYTHON_GROUPS.get(name,(None,)):
            command=[sys.executable,'-B',str(Path(__file__).resolve()),'--child',name]
            if group:command+=['--case-group',group]
            result=execute(command,env,PYTHON_TIMEOUTS.get(name,300))
            log='\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines()).rstrip()+'\n'
            label=name.replace('/','_')+('::'+group if group else '')
            (output/(label+'.log')).write_text(log)
            markers=[line for line in result.stdout.splitlines() if line.startswith('WEB_MODULE_RESULT ')]
            item=json.loads(markers[-1].partition(' ')[2]) if markers else {'tests':0,'failed':1,'skipped':0}
            item.update(file=name,returncode=result.returncode)
            if group:item['group']=group
            grouped.append(item);results.append(item)
            print(json.dumps({k:v for k,v in item.items() if k not in ('node_ids','all_node_ids')}),flush=True)
        if name in PYTHON_GROUPS and not check_group_coverage(grouped):
            item={'file':name,'group':'collection_coverage','returncode':1,'tests':0,'failed':1,'skipped':0}
            results.append(item);print(json.dumps(item),flush=True)
    for name in plan['javascript']:
        if args.match and not re.search(args.match, name): continue
        result = execute([env.get('TEST_NODE','node'),str(TESTS/name)],env,180)
        (output/(name+'.log')).write_text('\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines()).rstrip()+'\n')
        item = {'file':name,'returncode':result.returncode};results.append(item);print(json.dumps(item),flush=True)
    summary = {'inventory':plan,'full_profile':not bool(args.match),'results':results,
               'python_tests':sum(r.get('tests',0) for r in results),'skipped':sum(r.get('skipped',0) for r in results),
               'failed_modules':[r['file']+('::'+r['group'] if r.get('group') else '') for r in results if r['returncode'] or r.get('failed',0) or r.get('skipped',0)]}
    (output/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
    return int(not results or bool(summary['failed_modules']))


if __name__ == '__main__': raise SystemExit(main())
