"""Homepage reflection storage supports local files with PostgreSQL records."""
import tempfile
from pathlib import Path
from unittest.mock import patch

import db
from reflections.store import ReflectionsStore
from test_legacy_cloud_schema import PostgreSQLFixture


class LocalReflectionStartupTests(PostgreSQLFixture):
    def test_initialize_repeatably_and_read_compatible_shared_settings(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict('os.environ', {'PLAN_CONTENT_BACKEND': 'local'}):
            root = Path(temporary) / 'materials'
            root.mkdir()
            store = ReflectionsStore(root, Path(temporary) / 'runtime')
            with patch('plans.backup.database_snapshot', side_effect=AssertionError('No SQLite backup of PostgreSQL')):
                store.initialize()
                store.initialize()
            self.assertEqual(store.rows('reflection_entries'), [])
            self.assertEqual(store.get_setting('timeout', 30), 30)
            with db.connect() as connection:
                connection.execute('CREATE TABLE copilot_settings (id TEXT PRIMARY KEY,data TEXT)')
            self.assertEqual(store.get_setting('timeout', 30), 30)
            with db.connect() as connection:
                connection.execute('ALTER TABLE copilot_settings RENAME TO old_settings')
                connection.execute('CREATE TABLE copilot_settings (key TEXT PRIMARY KEY,value TEXT)')
                connection.execute('INSERT INTO copilot_settings VALUES (?,?)', ('timeout', '45'))
            self.assertEqual(store.get_setting('timeout', 30), 45)
