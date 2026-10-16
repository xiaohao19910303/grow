"""T05: protect externally changed mirrors using only synthetic temporary files."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from copilot.core import Problem, digest, encoded
from reflections.store import ReflectionsStore, render_markdown
from reflections.api import register


class ReflectionProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='grow-t05-')
        self.root = Path(self.tmp.name)
        (self.root / 'server').mkdir()
        self.s = ReflectionsStore(self.root, self.root / 'server/data.db')
        self.s.initialize()
        self.data = {'record_date': '2026-10-16', 'raw_text': 'original',
                     'prompt_kind': '自由记录', 'guided_answers': {}, 'tags': ['keep']}
        self.id = self.s.create(self.data, 'create-key')['id']

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self):
        return self.s.entry(self.id)

    def mirror(self):
        return self.s.path(self.entry()['path'])

    def organize_attempt(self):
        self.s._put('reflection_ai_attempts', 'ready-attempt',
                    {'id': 'ready-attempt', 'entry_id': self.id, 'kind': 'organize', 'status': 'ready',
                     'version_at_request': self.entry()['version'],
                     'sections': [{'kind': 'event', 'text': 'suggestion'}]})

    def action(self, kind):
        if kind == 'update':
            return self.s.update(self.id, {**self.data, 'base_version': self.entry()['version'],
                                           'raw_text': 'new'}, 'update-key')
        if kind == 'adopt':
            return self.s.adopt(self.id, 'ready-attempt', 'adopt-key')
        return getattr(self.s, kind)(self.id, kind + '-key')

    def test_all_rewriting_actions_reject_external_edits_without_changing_database(self):
        for kind in ('update', 'adopt', 'archive', 'restore'):
            with self.subTest(kind=kind):
                if kind == 'restore':
                    self.mirror().write_text(render_markdown(self.entry()))
                    self.s.archive(self.id, 'prepare-archive')
                self.organize_attempt()
                before = copy.deepcopy(self.entry())
                self.mirror().write_text('external personal content')
                with self.assertRaises(Problem) as ctx:
                    self.action(kind)
                self.assertEqual(ctx.exception.code, 'external_change')
                self.assertEqual(self.entry(), before)
                self.assertEqual(self.mirror().read_text(), 'external personal content')
                self.assertFalse(any(op['state'] == 'pending' for op in self.s.rows('reflection_operations')))

    def test_legacy_without_hash_is_accepted_only_when_file_matches(self):
        e = self.entry()
        e.pop('mirror_hash', None)
        self.s._put('reflection_entries', self.id, e)
        self.action('update')
        self.assertEqual(self.entry()['mirror_hash'], digest(self.mirror().read_bytes()))
        e = self.entry()
        e.pop('mirror_hash')
        self.s._put('reflection_entries', self.id, e)
        self.mirror().write_text('external old-format edit')
        with self.assertRaises(Problem):
            self.s.archive(self.id, 'legacy-conflict')
        self.assertNotIn('mirror_hash', self.entry())

    def test_missing_file_is_conflict_and_not_recreated(self):
        p = self.mirror()
        p.unlink()
        with self.assertRaises(Problem):
            self.action('update')
        self.assertFalse(p.exists())
        self.assertEqual(self.entry()['version'], 1)

    def test_baseline_tracks_successful_update_adopt_archive_and_restore(self):
        for action in ('update', 'adopt', 'archive', 'restore'):
            if action == 'adopt':
                self.organize_attempt()
            self.action(action)
            self.assertEqual(self.entry()['mirror_hash'], digest(self.mirror().read_bytes()))

    def test_interrupted_write_recovers_only_known_old_or_new_content(self):
        with patch.object(self.s, '_write_file', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.action('update')
        self.assertEqual(self.entry()['version'], 1)
        with self.s.lock():
            self.s.recover_locked()
        self.assertEqual(self.entry()['version'], 2)
        self.assertEqual(self.entry()['mirror_hash'], digest(self.mirror().read_bytes()))

    def test_external_change_after_failed_write_blocks_recovery(self):
        with patch.object(self.s, '_write_file', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.action('update')
        self.mirror().write_text('external after failure')
        with self.s.lock(), self.assertRaises(Problem):
            self.s.recover_locked()
        self.assertEqual(self.mirror().read_text(), 'external after failure')
        self.assertEqual(self.entry()['version'], 1)

    def test_conflict_inspection_is_read_only_and_keeps_both_versions(self):
        self.mirror().write_text('external text')
        before = copy.deepcopy(self.entry())
        report = self.s.mirror_status(self.id)
        self.assertTrue(report['conflict'])
        self.assertIn('original', report['saved_markdown'])
        self.assertEqual(report['file_markdown'], 'external text')
        self.assertEqual(self.entry(), before)
        self.mirror().unlink()
        self.assertIsNone(self.s.mirror_status(self.id)['file_markdown'])

    def test_file_written_but_record_not_committed_is_recovered_once(self):
        def interrupt(key):
            op = self.s.get('reflection_operations', key)
            for path, change in op['files'].items():
                self.s._write_file(path, change['content'], change['old'])
            raise OSError('interrupted after file replacement')

        with patch.object(self.s, '_resume', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.action('update')
        self.assertIn('new', self.mirror().read_text())
        self.assertEqual(self.entry()['version'], 1)
        with self.s.lock():
            self.s.recover_locked()
            self.s.recover_locked()
        self.assertEqual(self.entry()['version'], 2)
        self.assertEqual(self.entry()['mirror_hash'], digest(self.mirror().read_bytes()))

    def test_create_does_not_overwrite_an_existing_path(self):
        p = self.mirror()
        original = p.read_bytes()
        with self.assertRaises(Problem):
            self.s._write_file(self.entry()['path'], 'collision', None)
        self.assertEqual(p.read_bytes(), original)

    def test_crlf_external_edit_is_not_hidden_by_text_normalization(self):
        p = self.mirror()
        p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))
        self.assertTrue(self.s.mirror_status(self.id)['conflict'])
        with self.assertRaises(Problem):
            self.action('update')

    def test_unreadable_or_non_text_file_is_not_overwritten(self):
        p = self.mirror()
        for data in (b'\xff\xfe', b'x' * 200001):
            p.write_bytes(data)
            with self.assertRaises(Problem):
                self.s.mirror_status(self.id)
            with self.assertRaises(Problem):
                self.action('update')
            self.assertEqual(p.read_bytes(), data)
        p.unlink()
        p.mkdir()
        with self.assertRaises(Problem):
            self.action('update')
        self.assertTrue(p.is_dir())

    def test_api_exposes_read_only_conflict_without_model_call(self):
        api = FastAPI()
        register(api, self.root, self.s.db)

        @api.exception_handler(Problem)
        async def handler(request, error):
            return JSONResponse({'error': error.code, 'message': error.message}, status_code=error.status)

        self.mirror().write_text('external')
        with TestClient(api) as client:
            status = client.get('/api/reflections/' + self.id + '/file-status')
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()['file_markdown'], 'external')
            response = client.put('/api/reflections/' + self.id,
                                  json={**self.data, 'base_version': 1, 'key': 'api-update-key'},
                                  headers={'X-Copilot-Request': '1'})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['error'], 'external_change')
        self.assertEqual(self.mirror().read_text(), 'external')
        self.assertEqual(self.entry()['version'], 1)


if __name__ == '__main__':
    unittest.main()
