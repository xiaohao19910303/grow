"""Run temporary-workspace checks while denying writes to the real workspace."""
import argparse
import json
import os
import sys
import unittest
import fcntl
from pathlib import Path
from urllib.parse import unquote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test_*.py')
    args = parser.parse_args()
    server = Path(__file__).resolve().parents[1]
    workspace = server.parent.parent
    sys.path.insert(0, str(server))
    sys.dont_write_bytecode = True
    stats = {'sqlite_connections': 0, 'blocked_real_database_access': 0,
             'blocked_workspace_writes': 0}

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
    suite = unittest.defaultTestLoader.discover(str(server / 'tests'), pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('ISOLATION_AUDIT ' + json.dumps(stats, sort_keys=True))
    return 0 if result.wasSuccessful() and not any(
        stats[k] for k in ('blocked_real_database_access', 'blocked_workspace_writes')) else 1


if __name__ == '__main__':
    sys.exit(main())
