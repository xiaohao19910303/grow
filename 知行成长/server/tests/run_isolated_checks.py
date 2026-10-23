"""Run temporary-workspace checks while denying writes to the real workspace."""
import argparse
import json
import os
import sys
import unittest
import fcntl
import tempfile
from pathlib import Path
from urllib.parse import unquote


def setup_isolation():
    server = Path(__file__).resolve().parents[1]
    workspace = server.parent.parent
    sys.path.insert(0, str(server))
    # Subprocess browser fixtures need the same local package precedence.
    os.environ['PYTHONPATH'] = str(server) + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    runtime = tempfile.TemporaryDirectory(prefix='grow-test-runtime-')
    os.environ['RUNTIME_ROOT'] = runtime.name
    os.environ['LEARN_ROOT'] = runtime.name
    os.environ.pop('DATABASE_URL', None)
    dsn = os.getenv('TEST_POSTGRES_DSN') or os.getenv('TEST_LEGACY_PG_DSN') or os.getenv('TEST_GITHUB_PG_DSN')
    if dsn:
        for key in ('TEST_LEGACY_PG_DSN','TEST_GITHUB_PG_DSN','TEST_ACCOUNTS_PG_DSN'):
            os.environ[key] = dsn
    stats = {'sqlite_connections': 0, 'blocked_real_database_access': 0,
             'blocked_workspace_writes': 0, 'blocked_network_access': 0}

    def in_workspace(value, dir_fd=None):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        path = Path(os.fsdecode(value))
        if not path.is_absolute() and dir_fd is not None and dir_fd != -1:
            if hasattr(fcntl, 'F_GETPATH'):
                base = os.fsdecode(fcntl.fcntl(dir_fd, fcntl.F_GETPATH, b'\0' * 1024).split(b'\0')[0])
            else:
                base = os.readlink('/proc/self/fd/' + str(dir_fd))
            path = Path(base) / path
        return path.resolve().is_relative_to(workspace)

    def deny_write(value, dir_fd=None):
        if in_workspace(value, dir_fd):
            stats['blocked_workspace_writes'] += 1
            raise RuntimeError('隔离检查拒绝写入真实工作区。')

    def audit(event, values):
        if event == 'socket.connect' and isinstance(values[1],tuple) and values[1][0] not in ('127.0.0.1','localhost','::1'):
            stats['blocked_network_access'] += 1
            raise RuntimeError('隔离检查拒绝外部网络连接；请使用 HTTP 模拟器。')
        if event == 'sqlite3.connect':
            stats['sqlite_connections'] += 1
            target = os.fsdecode(values[0])
            if target.startswith('file:'):
                target = unquote(target[5:].split('?', 1)[0])
            if target != ':memory:' and in_workspace(target):
                stats['blocked_real_database_access'] += 1
                raise RuntimeError('隔离检查拒绝访问真实工作区数据库。')
        elif event == 'open':
            flags = values[2] or 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                deny_write(values[0])
        elif event in ('os.remove', 'os.rmdir'):
            deny_write(values[0], values[1])
        elif event in ('os.mkdir', 'os.chmod'):
            deny_write(values[0], values[2])
        elif event == 'os.utime':
            deny_write(values[0], values[3])
        elif event == 'os.truncate':
            deny_write(values[0])
        elif event == 'os.rename':
            deny_write(values[0], values[2])
            deny_write(values[1], values[3])
        elif event == 'os.symlink':
            deny_write(values[1], values[2])
        elif event == 'os.link':
            deny_write(values[1], values[3])

    sys.addaudithook(audit)
    import psycopg2
    from psycopg2.extensions import parse_dsn
    connect = psycopg2.connect
    def isolated_connect(dsn=None, *args, **kwargs):
        settings = {**parse_dsn(dsn or ''), **kwargs}
        if settings.get('host') not in ('127.0.0.1','localhost','::1'):
            stats['blocked_real_database_access'] += 1
            raise RuntimeError('隔离检查只允许连接 localhost PostgreSQL。')
        return connect(dsn, *args, **kwargs)
    psycopg2.connect = isolated_connect
    return stats,runtime,server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--full',action='store_true',help='Run every Python and JavaScript check, including Chromium; skips fail the run.')
    args = parser.parse_args()
    if args.full:
        if args.pattern!='test_*.py':parser.error('--full cannot restrict test patterns')
        if not (os.getenv('TEST_POSTGRES_DSN') or os.getenv('TEST_LEGACY_PG_DSN') or os.getenv('TEST_GITHUB_PG_DSN')):
            parser.error('--full requires TEST_POSTGRES_DSN pointing to disposable localhost PostgreSQL')
        for key in ('RUN_GITHUB_BROWSER','RUN_LEGACY_BROWSER','RUN_ACCOUNTS_BROWSER'):os.environ[key]='1'
    stats,runtime,server=setup_isolation()
    try:
        suite = unittest.defaultTestLoader.discover(str(server / 'tests'), pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        javascript_ok=True
        javascript=[]
        if args.full and result.wasSuccessful():
            import subprocess
            for script in sorted((server/'tests').glob('test_*.cjs')):
                completed=subprocess.run([os.getenv('TEST_NODE','node'),str(script)],cwd=server,
                                         env={**os.environ,'TEST_PYTHON':sys.executable})
                javascript.append({'file':script.name,'returncode':completed.returncode})
                javascript_ok=javascript_ok and completed.returncode==0
    finally:runtime.cleanup()
    print('ISOLATION_AUDIT ' + json.dumps(stats, sort_keys=True))
    print('REGRESSION_RESULT '+json.dumps({'python_tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'javascript':javascript}))
    return 0 if result.testsRun>0 and result.wasSuccessful() and javascript_ok and not (args.full and result.skipped) and not any(
        stats[k] for k in ('blocked_real_database_access', 'blocked_workspace_writes','blocked_network_access')) else 1


if __name__ == '__main__':
    sys.exit(main())
