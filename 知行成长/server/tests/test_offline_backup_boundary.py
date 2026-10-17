"""Offline SQLite archives remain separate from the remote PostgreSQL database."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from copilot.core import Problem, digest
from plans.backup import database_snapshot, validate


class OfflineBackupBoundary(unittest.TestCase):
    def test_snapshot_targets_archive_and_validation_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); source = folder/'source.db'
            @contextmanager
            def conn():
                with sqlite3.connect(source) as c:
                    yield c
            with conn() as c:
                c.execute('CREATE TABLE records (text TEXT)')
                c.execute("INSERT INTO records VALUES ('PRIVATE TEST RECORD')")
                c.execute('CREATE TABLE copilot_settings (key TEXT,value TEXT)')
                c.execute("INSERT INTO copilot_settings VALUES ('api_key','OLD_TEST_SECRET')")
            database_snapshot(SimpleNamespace(conn=conn),folder/'data.db')
            with sqlite3.connect(folder/'data.db') as archive:
                self.assertEqual(archive.execute('SELECT text FROM records').fetchone()[0],'PRIVATE TEST RECORD')
                self.assertEqual(archive.execute('SELECT count(*) FROM copilot_settings').fetchone()[0],0)
            with conn() as c:
                self.assertEqual(c.execute('SELECT value FROM copilot_settings').fetchone()[0],'OLD_TEST_SECRET')
            (folder/'manifest.json').write_text(json.dumps({'version':2,'files':{},'database_hash':digest((folder/'data.db').read_bytes())}))
            self.assertEqual(validate(folder)[0],folder.resolve())

    def test_postgresql_does_not_create_a_fake_sqlite_archive(self):
        @contextmanager
        def conn():
            yield object()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'data.db'
            with self.assertRaises(Problem) as error:
                database_snapshot(SimpleNamespace(conn=conn),target)
            self.assertEqual(error.exception.code,'remote_backup')
            self.assertFalse(target.exists())
