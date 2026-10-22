"""Standalone web profile: all discovered web tests, isolated by module; no Zook required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SERVER = Path(__file__).resolve().parents[1]
TESTS = SERVER / 'tests'
CONNECTION_TESTS = {'test_action_source_http.py': 'Requires the separate Zook HTTP/PG fixture; deferred connection profile.'}


def inventory():
    python = sorted(p.relative_to(TESTS).as_posix() for p in TESTS.rglob('test_*.py'))
    return {'profile': 'standalone-web', 'python': [p for p in python if p not in CONNECTION_TESTS],
            'javascript': sorted(p.name for p in TESTS.glob('test_*.cjs')),
            'deferred_connection': [{'file': p, 'reason': why} for p, why in CONNECTION_TESTS.items() if p in python]}


def child(filename):
    sys.path.insert(0, str(TESTS))
    from run_isolated_checks import setup_isolation
    stats, runtime, _ = setup_isolation()
    try:
        import pytest
        class Counts:
            collected = 0
            failed = 0
            skipped = 0
            def pytest_collection_finish(self, session): self.collected = len(session.items)
            def pytest_runtest_logreport(self, report):
                if report.failed: self.failed += 1
                if report.skipped: self.skipped += 1
        counts = Counts()
        code = pytest.main(['-q', '-p', 'no:cacheprovider', '--import-mode=importlib', str(TESTS / filename)], plugins=[counts])
        summary = {'tests': counts.collected, 'failed': counts.failed, 'skipped': counts.skipped,
                   'exit_code': int(code), 'isolation': stats}
        print('WEB_MODULE_RESULT ' + json.dumps(summary), flush=True)
        return int(bool(code or counts.failed or counts.skipped or not counts.collected or any(v for k,v in stats.items() if k.startswith('blocked_'))))
    finally:
        runtime.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--match', help='Diagnostic subset; never labelled full profile.')
    parser.add_argument('--child', help=argparse.SUPPRESS)
    parser.add_argument('--output', default='/tmp/grow-web-regression')
    args = parser.parse_args()
    plan = inventory()
    if args.list:
        print(json.dumps(plan, indent=2)); return 0
    if args.child:
        if args.child not in plan['python']: parser.error('Unknown web test module')
        return child(args.child)
    dsn = os.getenv('TEST_POSTGRES_DSN', '')
    if 'host=127.0.0.1' not in dsn: parser.error('Requires explicit TEST_POSTGRES_DSN for disposable localhost PostgreSQL')
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if k not in ('DATABASE_URL','GROW_ACTION_BRIDGE_SECRET','LIGHTTICK_BRIDGE_URL')}
    env.update(TEST_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               ACTION_P0_EVIDENCE_DIR=str(output/'screenshots'), RUN_GITHUB_BROWSER='1', RUN_LEGACY_BROWSER='1', RUN_ACCOUNTS_BROWSER='1')
    for name in ('TEST_LEGACY_PG_DSN','TEST_GITHUB_PG_DSN','TEST_ACCOUNTS_PG_DSN'): env[name] = dsn
    results = []
    for name in plan['python']:
        if args.match and args.match not in name: continue
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', name], cwd=SERVER, env=env,
                                capture_output=True, text=True, timeout=300)
        log = '\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines()).rstrip()+'\n'
        (output/(name.replace('/','_')+'.log')).write_text(log)
        markers = [line for line in result.stdout.splitlines() if line.startswith('WEB_MODULE_RESULT ')]
        item = json.loads(markers[-1].partition(' ')[2]) if markers else {'tests':0,'failed':1,'skipped':0}
        item.update(file=name, returncode=result.returncode); results.append(item); print(json.dumps(item), flush=True)
    for name in plan['javascript']:
        if args.match and args.match not in name: continue
        result = subprocess.run([env.get('TEST_NODE','node'),str(TESTS/name)],cwd=SERVER,env=env,capture_output=True,text=True,timeout=180)
        (output/(name+'.log')).write_text('\n'.join(line.rstrip() for line in (result.stdout+result.stderr).splitlines()).rstrip()+'\n')
        item = {'file':name,'returncode':result.returncode};results.append(item);print(json.dumps(item),flush=True)
    summary = {'inventory':plan,'full_profile':not bool(args.match),'results':results,
               'python_tests':sum(r.get('tests',0) for r in results),'skipped':sum(r.get('skipped',0) for r in results),
               'failed_modules':[r['file'] for r in results if r['returncode'] or r.get('failed',0) or r.get('skipped',0)]}
    (output/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
    return int(not results or bool(summary['failed_modules']))


if __name__ == '__main__': raise SystemExit(main())
