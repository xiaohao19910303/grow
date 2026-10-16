"""P0 backups use only synthetic workspaces and temporary SQLite databases."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from copilot.core import Problem, digest, encoded
from plans import backup
from plans.store import Plans
from reflections.store import ReflectionsStore


class PlatformBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='grow-p0-test-')
        self.base = Path(self.tmp.name)
        self.root = self.base / 'workspace'
        (self.root / 'server').mkdir(parents=True)
        self.store = Plans(self.root, self.root / 'server/data.db')
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text='sample'):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def snapshot(self):
        with self.store.lock():
            return backup.snapshot(self.store)

    def manifest(self, result):
        return json.loads((Path(result['path']) / 'manifest.json').read_text())

    def legacy_snapshot(self):
        """Construct a real v1 fixture independently of the new snapshot writer."""
        folder = self.base / 'v1'
        (folder / 'files/执行复盘').mkdir(parents=True)
        rel = '执行复盘/2026-10-13.md'
        (folder / 'files' / rel).write_text('original', encoding='utf-8')
        with closing(sqlite3.connect(self.store.db)) as src, closing(sqlite3.connect(folder / 'data.db')) as dst:
            src.backup(dst)
        m = {'version': 1, 'created_at': '2026-10-15',
             'files': {rel: digest('original')},
             'database_hash': digest((folder / 'data.db').read_bytes())}
        (folder / 'manifest.json').write_text(encoded(m), encoding='utf-8')
        return folder

    def test_root_documents_and_new_attachment_formats_are_backed_up(self):
        expected = ['长期成长学习体系总规划.md', '知识索引.md',
                    '知行成长/平台演进规划.md', '知行成长/数据边界与备份规则.md',
                    '执行复盘/附件/说明.txt', '认知阅读/阅读笔记/chart.svg',
                    '学习计划/附件/audio.m4a']
        for rel in expected:
            self.write(rel)
        result = self.snapshot()
        m = self.manifest(result)
        self.assertEqual(m['version'], 2)
        self.assertTrue(set(expected).issubset(m['files']))
        backup.validate(result['path'])

    def test_uncovered_files_and_sensitive_paths_are_reported(self):
        for rel in ['执行复盘/附件/unknown.xyz', '执行复盘/.env',
                    '执行复盘/secret.key', '执行复盘/.private/token.json',
                    '未登记笔记.md', '新主题/资料.md', '知行成长/server/.env']:
            self.write(rel)
        result = self.snapshot()
        m = self.manifest(result)
        excluded = {item['path']: item['reason'] for item in m['excluded']}
        self.assertIn('执行复盘/附件/unknown.xyz', excluded)
        self.assertIn('执行复盘/.env', excluded)
        self.assertIn('执行复盘/secret.key', excluded)
        self.assertIn('执行复盘/.private', excluded)
        self.assertIn('未登记笔记.md', excluded)
        self.assertIn('新主题', excluded)
        self.assertNotIn('执行复盘/.env', m['files'])
        self.assertNotIn('知行成长/server/.env', m['files'])
        self.assertEqual(result['excluded'], m['excluded'])

    def test_v1_restore_preserves_new_scope_files(self):
        folder = self.legacy_snapshot()
        preserved = ['长期成长学习体系总规划.md', '知行成长/平台演进规划.md',
                     '执行复盘/附件/chart.svg', '执行复盘/附件/unknown.xyz']
        for rel in preserved:
            self.write(rel, 'keep')
        old = self.write('执行复盘/2026-10-13.md', 'changed')
        self.write('执行复盘/new.md', 'remove within v1 scope')
        pv = backup.preview(self.store, folder)
        self.assertTrue(set(preserved).isdisjoint(pv['changes']))
        backup.restore(self.store, folder, pv['token'])
        self.assertEqual(old.read_text(), 'original')
        self.assertFalse((self.root / '执行复盘/new.md').exists())
        for rel in preserved:
            self.assertEqual((self.root / rel).read_text(), 'keep')

    def test_v2_restore_reports_and_preserves_unsupported_files(self):
        self.write('执行复盘/原文.md', 'original')
        b = self.snapshot()
        self.write('执行复盘/原文.md', 'changed')
        self.write('执行复盘/new.md', 'new')
        self.write('执行复盘/附件/unknown.xyz', 'keep')
        pv = backup.preview(self.store, b['path'])
        self.assertIn('执行复盘/附件/unknown.xyz',
                      [x['path'] for x in pv['excluded']])
        r = backup.restore(self.store, b['path'], pv['token'])
        self.assertTrue(Path(r['before']['path']).exists())
        self.assertEqual((self.root / '执行复盘/原文.md').read_text(), 'original')
        self.assertFalse((self.root / '执行复盘/new.md').exists())
        self.assertEqual((self.root / '执行复盘/附件/unknown.xyz').read_text(), 'keep')

    def test_rejects_credential_path_even_with_valid_hash(self):
        b = self.snapshot()
        folder = Path(b['path'])
        p = folder / 'files/执行复盘/.env'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('test-only')
        m = self.manifest(b)
        m['files']['执行复盘/.env'] = digest('test-only')
        (folder / 'manifest.json').write_text(encoded(m))
        with self.assertRaises(Problem):
            backup.validate(folder)

    def test_independent_copy_restores_files_versions_tags_and_all_tables(self):
        """Full drill: source, copied backup and fresh receiver are separate paths."""
        reflections = ReflectionsStore(self.root, self.store.db)
        reflections.initialize()
        payload = {'record_date': '2026-10-16', 'raw_text': '第一版原文',
                   'prompt_kind': '自由记录', 'guided_answers': {}, 'tags': ['练习']}
        rec = reflections.create(payload, 'drill-create')
        reflections.update(rec['id'], {**payload, 'base_version': 1,
                                      'raw_text': '第二版原文'}, 'drill-update')
        self.write('执行复盘/2026-10-13.md', '# 旧复盘\n保留原始依据')
        self.write('认知阅读/阅读笔记/note.md', '[复盘](../../执行复盘/2026-10-13.md)')
        self.write('长期成长学习体系总规划.md', '# 个人长期规划')
        self.write('知行成长/平台演进规划.md', '# 平台规划')
        self.write('学习计划/附件/chart.svg', '<svg></svg>')
        self.write('学习计划/plan-20261016-001/学习记录.md', '# 本人练习与反馈')
        with self.store.conn() as c:
            c.executescript('''
                CREATE TABLE reviews (id INTEGER PRIMARY KEY, date TEXT, thought TEXT);
                CREATE TABLE decisions (id INTEGER PRIMARY KEY, reason TEXT);
                CREATE TABLE todos (id TEXT PRIMARY KEY, date TEXT, title TEXT, done INTEGER);
                CREATE TABLE stock_records (id TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE copilot_learning_records (id TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE copilot_settings (key TEXT PRIMARY KEY, value TEXT);
            ''')
            c.execute('INSERT INTO reviews VALUES (17,?,?)', ('2026-10-13', '旧四问'))
            c.execute('INSERT INTO decisions VALUES (23,?)', ('当时理由',))
            c.execute('INSERT INTO todos VALUES (?,?,?,?)', ('todo-1', '2026-10-16', '实践', 0))
            c.execute('INSERT INTO stock_records VALUES (?,?)',
                      ('stock-1', encoded({'tags': ['投资练习'], 'related_decision_id': 23})))
            c.execute('INSERT INTO copilot_learning_records VALUES (?,?)',
                      ('lesson-1', encoded({'state': 'completed', 'comment': '本人反馈'})))
            c.execute('INSERT INTO copilot_settings VALUES (?,?)', ('api_key', 'TEST_SECRET_ONLY'))
            c.execute('INSERT INTO learning_plans VALUES (?,?)',
                      ('plan-20261016-001', encoded({'name': '测试计划', 'version': 1})))
            c.execute('INSERT INTO learning_plan_versions VALUES (?,?,?)',
                      ('plan-20261016-001', 1, encoded({'title': '原始规划'})))
            c.execute('INSERT INTO learning_lessons VALUES (?,?,?)',
                      ('plan-20261016-001', 1, encoded({'topic': '练习课'})))
            c.execute('INSERT INTO learning_feedback VALUES (?,?,?)',
                      ('plan-20261016-001', 1, encoded({'state': 'completed', 'comment': '真实使用样本以外的隔离反馈'})))
            expected_tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        b = self.snapshot()
        self.assertNotIn(b'TEST_SECRET_ONLY', (Path(b['path']) / 'data.db').read_bytes())
        with self.store.conn() as c:
            self.assertEqual(c.execute('SELECT value FROM copilot_settings').fetchone()[0], 'TEST_SECRET_ONLY')
        independent = self.base / 'independent-copy'
        shutil.copytree(b['path'], independent)
        # Make the source path unavailable: the copy must stand on its own.
        self.root.rename(self.base / 'source-offline')
        backup.validate(independent)
        receiver_root = self.base / 'receiver'
        (receiver_root / 'server').mkdir(parents=True)
        receiver = Plans(receiver_root, receiver_root / 'server/data.db')
        receiver.initialize()
        pv = backup.preview(receiver, independent)
        result = backup.restore(receiver, independent, pv['token'])
        self.assertTrue(Path(result['before']['path']).is_dir())
        for rel, h in self.manifest({'path': independent})['files'].items():
            self.assertEqual(digest((receiver_root / rel).read_bytes()), h)
        recovered = ReflectionsStore(receiver_root, receiver.db)
        self.assertEqual(recovered.entry(rec['id'])['raw_text'], '第二版原文')
        self.assertEqual(recovered.entry(rec['id'])['tags'], ['练习'])
        self.assertEqual(len(recovered.versions(rec['id'])), 2)
        with receiver.conn() as c:
            recovered_dump = '\n'.join(c.iterdump())
            self.assertEqual({r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}, expected_tables)
            self.assertEqual(c.execute('SELECT thought FROM reviews WHERE id=17').fetchone()[0], '旧四问')
            self.assertEqual(c.execute('SELECT reason FROM decisions WHERE id=23').fetchone()[0], '当时理由')
            self.assertEqual(c.execute('SELECT done FROM todos WHERE id="todo-1"').fetchone()[0], 0)
            self.assertEqual(json.loads(c.execute('SELECT data FROM stock_records').fetchone()[0])['related_decision_id'], 23)
            self.assertEqual(json.loads(c.execute('SELECT data FROM copilot_learning_records').fetchone()[0])['state'], 'completed')
            self.assertIsNone(c.execute("SELECT value FROM copilot_settings WHERE key='api_key'").fetchone())
        with closing(sqlite3.connect(independent / 'data.db')) as c:
            self.assertEqual(recovered_dump, '\n'.join(c.iterdump()))
        self.assertFalse((receiver.runtime / 'restore-pending.json').exists())

    def test_corrupted_missing_database_and_file_are_rejected(self):
        self.write('执行复盘/原文.md')
        b = self.snapshot()
        original = Path(b['path'])
        for mode in ('file-corrupt', 'file-missing', 'db-corrupt', 'db-missing'):
            with self.subTest(mode=mode):
                folder = self.base / mode
                shutil.copytree(original, folder)
                p = folder / ('files/执行复盘/原文.md' if mode.startswith('file') else 'data.db')
                if mode.endswith('missing'):
                    p.unlink()
                else:
                    p.write_bytes(b'corrupt')
                with self.assertRaises(Problem):
                    backup.validate(folder)

    def test_unsafe_manifest_paths_and_symlinks_are_rejected(self):
        self.write('执行复盘/原文.md')
        b = self.snapshot()
        folder = Path(b['path'])
        original = self.manifest(b)
        for rel in ('../outside.md', '/tmp/outside.md', '执行复盘/../outside.md',
                    '知行成长/server/data.db', '执行复盘/./原文.md'):
            with self.subTest(rel=rel):
                m = {**original, 'files': {rel: digest('sample')}}
                (folder / 'manifest.json').write_text(encoded(m))
                with self.assertRaises(Problem):
                    backup.validate(folder)
        (folder / 'manifest.json').write_text(encoded(original))
        source = folder / 'files/执行复盘/原文.md'
        source.unlink()
        source.symlink_to(self.root / '执行复盘/原文.md')
        with self.assertRaises(Problem):
            backup.validate(folder)

    def test_source_symlink_blocks_backup(self):
        source = self.write('执行复盘/原文.md')
        (source.parent / 'link.md').symlink_to(source)
        with self.assertRaises(Problem):
            self.snapshot()

    def test_stale_preview_for_file_or_database_is_rejected(self):
        self.write('执行复盘/原文.md')
        b = self.snapshot()
        token = backup.preview(self.store, b['path'])['token']
        self.write('执行复盘/原文.md', 'new')
        with self.assertRaises(Problem):
            backup.restore(self.store, b['path'], token)
        token = backup.preview(self.store, b['path'])['token']
        with self.store.conn() as c:
            c.execute('CREATE TABLE later_records (id INTEGER)')
        pv = backup.preview(self.store, b['path'])
        self.assertIn('later_records', pv['database_tables_removed'])
        with self.assertRaises(Problem):
            backup.restore(self.store, b['path'], token)

    def test_interrupted_restore_keeps_journal_before_snapshot_and_blocks_restart(self):
        self.write('执行复盘/a.md', 'original first')
        self.write('执行复盘/原文.md', 'original')
        b = self.snapshot()
        self.write('执行复盘/a.md', 'new first')
        self.write('执行复盘/原文.md', 'new')
        pv = backup.preview(self.store, b['path'])
        replace = backup.os.replace
        calls = 0

        def fail_second(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated write failure after first file')
            return replace(src, dst)

        with patch.object(backup.os, 'replace', side_effect=fail_second):
            with self.assertRaises(OSError):
                backup.restore(self.store, b['path'], pv['token'])
        journal_path = self.store.runtime / 'restore-pending.json'
        journal = json.loads(journal_path.read_text())
        before, _ = backup.validate(journal['before']['path'])
        self.assertEqual((before / 'files/执行复盘/原文.md').read_text(), 'new')
        self.assertEqual((before / 'files/执行复盘/a.md').read_text(), 'new first')
        self.assertEqual((self.root / '执行复盘/a.md').read_text(), 'original first')
        self.assertEqual((self.root / '执行复盘/原文.md').read_text(), 'new')
        with self.assertRaises(Problem):
            self.store.initialize()
        with self.assertRaises(Problem):
            backup.restore(self.store, b['path'], pv['token'])
        self.assertTrue(journal_path.exists())

    def test_unreadable_directory_must_not_silently_disappear(self):
        self.write('执行复盘/原文.md')
        scandir = backup.os.scandir

        def deny_module(path):
            if Path(path) == self.root / '执行复盘':
                raise PermissionError('denied')
            return scandir(path)

        with patch.object(backup.os, 'scandir', side_effect=deny_module):
            with self.assertRaises((OSError, Problem)):
                self.snapshot()


if __name__ == '__main__':
    unittest.main()
