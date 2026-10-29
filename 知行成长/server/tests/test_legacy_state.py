"""T04 checks: temporary database only; no application lifespan or real service."""
import copy
import json
import tempfile
import unittest
import asyncio
import threading
import httpx
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as dashboard
from cloud_fixtures import CloudFixture
from copilot.core import Problem, digest, encoded
from fastapi import FastAPI
from fastapi.testclient import TestClient
from legacy_state import patch_state, initialize_requests, REQUIRED


class LegacyStateTests(CloudFixture):
    def setUp(self):
        super().setUp()
        dashboard.init_db()
        dashboard.save_state({'modules': dashboard.DEFAULT_MODULES})

    def save(self, state):
        return dashboard.save_state(state, require_revision=True)

    def seeded(self):
        s = dashboard.load_state()
        for key in ('decisions', 'predictions', 'reviews', 'insights'):
            s[key] = [{'date': '2026-10-16', 'title': 'decision', 'statement': 'prediction',
                       'thought': 'review', 'insight': 'insight'}]
        s['customRecords'] = [{'value': 'custom'}]
        self.save(s)
        return dashboard.load_state()

    def request(self, state, changes, key='incremental-save-key'):
        return {'key': key, 'changes': changes,
                'base_revisions': {k: state['_section_revisions'][k] for k in changes}}

    def incremental(self, request):
        return patch_state(dashboard.get_conn, request)

    def row_versions(self):
        with closing(dashboard.get_conn()) as conn, conn:
            return {table: sorted((r[0], r[1]) for r in conn.execute(
                f'SELECT row_to_json(t)::text,xmin::text FROM {table} t'))
                for table in ('modules', 'checkins', 'habits', 'custom_fields', 'custom_records',
                              'todos', 'decisions', 'predictions', 'reviews', 'insights')}

    def test_unchanged_put_and_unrelated_patch_do_not_rewrite_rows(self):
        state = self.seeded()
        state.update(checkins={'2026-10-29': {'renzhi': 2}},
                     habits={'2026-10-29': {'minutes': 10, 'note': 'keep'}},
                     customFields=[{'key': 'value', 'label': '值', 'type': 'text'}],
                     todos=[{'id': 'todo', 'date': '2026-10-29', 'title': 'keep', 'done': False}])
        self.save(state)
        state = dashboard.load_state()
        versions = self.row_versions()
        self.save(state)
        self.assertEqual(self.row_versions(), versions)
        changed = copy.deepcopy(state['reviews'])
        changed[0]['thought'] = 'only this row changes'
        result = self.incremental(self.request(state, {'reviews': changed}))
        after = self.row_versions()
        for table in versions:
            if table != 'reviews': self.assertEqual(after[table], versions[table], table)
        self.assertNotEqual(after['reviews'], versions['reviews'])
        self.assertNotIn('state', result)
        self.assertEqual(result['_revision'], dashboard.load_state()['_revision'])

    def test_old_put_keeps_numeric_text_keys_and_empty_keys_compatible(self):
        state = dashboard.load_state()
        state['todos'] = [{'id': 123, 'date': '2026-10-29', 'title': 'old import'},
                          {'id': '', 'date': '2026-10-29', 'title': 'old empty text key'}]
        self.save(state)
        saved = dashboard.load_state()
        self.assertEqual({r['id'] for r in saved['todos']}, {'123', ''})
        before = self.row_versions()
        self.save(saved)
        self.assertEqual(self.row_versions(), before)

    def test_disjoint_sections_merge_but_same_section_conflicts(self):
        state = self.seeded()
        first = self.request(state, {'habits': {'2026-10-29': {'minutes': 15}}}, 'parallel-habit')
        second = self.request(state, {'todos': [{'id': 'todo', 'date': '2026-10-29', 'title': 'keep'}]}, 'parallel-todo')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.incremental, (first, second)))
        self.assertTrue(all(r['ok'] for r in results))
        current = dashboard.load_state()
        self.assertEqual(current['habits']['2026-10-29']['minutes'], 15)
        self.assertEqual(current['todos'][0]['title'], 'keep')
        with self.assertRaises(Problem) as conflict:
            self.incremental(self.request(state, {'todos': []}, 'stale-todo-key'))
        self.assertEqual(conflict.exception.code, 'state_conflict')
        with self.assertRaises(Problem): self.save(state)

    def test_response_lost_and_concurrent_replay_allocate_once(self):
        state = dashboard.load_state()
        request = self.request(state, {'reviews': [{'thought': 'PRIVATE DRAFT', '_client_id': 'draft-id'}]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.incremental, (request, request)))
        self.assertEqual(results[0], results[1])
        saved = dashboard.load_state()
        self.assertEqual(len(saved['reviews']), 1)
        self.assertEqual(results[0]['assigned_ids']['reviews']['draft-id'], saved['reviews'][0]['id'])
        # An old acknowledgement stays immutable even after a later edit/deletion.
        self.incremental(self.request(saved, {'reviews': []}, 'delete-after-replay'))
        self.assertEqual(self.incremental(request), results[0])
        self.assertEqual(dashboard.load_state()['reviews'], [])
        bad = copy.deepcopy(request);bad['changes']['reviews'][0]['thought'] = 'changed'
        with self.assertRaises(Problem) as conflict: self.incremental(bad)
        self.assertEqual(conflict.exception.code, 'request_conflict')
        with closing(dashboard.get_conn()) as conn, conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM legacy_state_requests')]
        self.assertNotIn('PRIVATE DRAFT', json.dumps(rows))

    def test_invalid_scope_or_identity_does_not_write_any_section(self):
        state = self.seeded()
        examples = [self.request(state, {'reviews': [{'thought': 'no identity'}]}),
                    self.request(state, {'reviews': [{'id': 999999}]}),
                    self.request(state, {'reviews': ['malformed']}),
                    self.request(state, {'habits': [], 'reviews': []})]
        examples.append({'key': 'wrong-scope', 'changes': {'reflection_entries': []}, 'base_revisions': {'reflection_entries': 'x'}})
        examples.append(self.request(state, {'habits': {'2026-10-29': {'minutes': 10}}, 'reviews': [{'id': 999999}]}))
        for request in examples:
            with self.subTest(request=request):
                with self.assertRaises(Problem): self.incremental(request)
                self.assertEqual(dashboard.load_state(), state)

    def test_receipt_failure_rolls_back_records_and_can_retry_same_key(self):
        state = self.seeded()
        with closing(dashboard.get_conn()) as conn, conn:
            initialize_requests(conn)
            conn.execute("ALTER TABLE legacy_state_requests ADD CONSTRAINT reject_receipt CHECK(response='reject')")
        request = self.request(state, {'reviews': [{'thought': 'retry me', '_client_id': 'retry-draft'}]})
        with self.assertRaises(Problem): self.incremental(request)
        self.assertEqual(dashboard.load_state(), state)
        with closing(dashboard.get_conn()) as conn, conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM legacy_state_requests').fetchone()[0], 0)
            conn.execute('ALTER TABLE legacy_state_requests DROP CONSTRAINT reject_receipt')
        self.assertTrue(self.incremental(request)['ok'])
        self.assertEqual(len(dashboard.load_state()['reviews']), 1)

    def test_explicit_reset_still_clears_only_old_tables(self):
        state = self.seeded()
        self.assertEqual(state['_revision'], digest(encoded({k:state[k] for k in REQUIRED})))
        from ai_evidence import freeze
        with closing(dashboard.get_conn()) as conn, conn:
            frozen = freeze(conn, 'behavior-report', 'before-incremental',
                            [{'role':'user','content':'PRIVATE FROZEN INPUT'}], 'fixture')
            conn.execute('CREATE TABLE unrelated_private_notes (id TEXT PRIMARY KEY, body TEXT)')
            conn.execute("INSERT INTO unrelated_private_notes VALUES ('note', 'PRIVATE ORIGINAL')")
        self.incremental(self.request(state, {'reviews': []}))
        current = dashboard.load_state()
        empty = {k: {} if k in ('checkins', 'habits') else [] for k in REQUIRED}
        empty['_revision'] = current['_revision']
        self.save(empty)
        self.assertTrue(all(not dashboard.load_state()[k] for k in REQUIRED))
        with closing(dashboard.get_conn()) as conn, conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM legacy_state_requests').fetchone()[0], 1)
            stored = json.loads(conn.execute('SELECT data FROM ai_evidence_snapshots WHERE id=?', (frozen['id'],)).fetchone()[0])
            self.assertEqual(stored['messages'], frozen['messages'])
            self.assertEqual(conn.execute('SELECT body FROM unrelated_private_notes').fetchone()[0], 'PRIVATE ORIGINAL')

    def test_patch_http_protocol_and_worker_context(self):
        api = FastAPI()
        api.patch('/api/data')(dashboard.patch_data)
        api.put('/api/data')(dashboard.put_data)
        with TestClient(api) as client:
            state = dashboard.load_state()
            request = self.request(state, {'reviews': []})
            self.assertEqual(client.patch('/api/data', json=request).status_code, 409)
            response = client.patch('/api/data', json=request, headers={'X-Legacy-State-Protocol': '2'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(client.patch('/api/data', content='{', headers={'X-Legacy-State-Protocol': '2'}).status_code, 422)
        from tenancy import current_user
        async def run():
            loop_thread = threading.get_ident()
            token = current_user.set({'id': 'worker-context-test'})
            def writer(*args, **kwargs):
                self.assertNotEqual(threading.get_ident(), loop_thread)
                self.assertEqual(current_user.get()['id'], 'worker-context-test')
                return {'ok': True}
            try:
                with patch.object(dashboard, 'patch_legacy_state', writer), patch.object(dashboard, 'save_state', writer):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url='http://localhost') as client:
                        for method, protocol in (('PATCH', '2'), ('PUT', '1')):
                            response = await client.request(method, '/api/data', json={}, headers={'X-Legacy-State-Protocol': protocol})
                            self.assertEqual(response.status_code, 200)
            finally: current_user.reset(token)
        asyncio.run(run())

    def test_identity_survives_multiple_edits_and_unrelated_saves(self):
        s = self.seeded()
        ids = {k: s[k][0]['id'] for k in ('decisions', 'predictions', 'reviews', 'insights')}
        custom_id = s['customRecords'][0]['_record_id']
        for n in range(3):
            s['decisions'][0]['title'] = 'edited-' + str(n)
            s['customRecords'][0]['value'] = 'edited-' + str(n)
            s['todos'] = [{'id': 'todo', 'date': '2026-10-16', 'title': str(n), 'done': False}]
            self.save(s)
            s = dashboard.load_state()
            self.assertEqual({k: s[k][0]['id'] for k in ids}, ids)
            self.assertEqual(s['customRecords'][0]['_record_id'], custom_id)

    def test_stale_page_cannot_erase_other_page_or_import(self):
        s = self.seeded()
        old = copy.deepcopy(s)
        s['reviews'][0]['thought'] = 'new page'
        self.save(s)
        with self.assertRaises(Problem):
            self.save(old)
        stale = dashboard.load_state()
        with closing(dashboard.get_conn()) as c, c:
            c.execute("INSERT INTO insights(date,insight,source) VALUES ('2026-10-16','imported','md')")
        with self.assertRaises(Problem):
            self.save(stale)
        current = dashboard.load_state()
        self.assertEqual(current['reviews'][0]['thought'], 'new page')
        self.assertEqual(len(current['insights']), 2)

    def test_concurrent_writers_only_one_snapshot_wins(self):
        s = self.seeded()

        def write(n):
            candidate = copy.deepcopy(s)
            candidate['reviews'][0]['thought'] = str(n)
            try:
                self.save(candidate)
                return 'saved'
            except Problem:
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, (1, 2)))
        self.assertEqual(sorted(results), ['conflict', 'saved'])

    def test_missing_revision_duplicate_or_unknown_identity_rolls_back(self):
        state = self.seeded()
        for mutation in ('missing', 'duplicate', 'unknown', 'incomplete', 'malformed', 'bad-field'):
            with self.subTest(mutation=mutation):
                s = copy.deepcopy(state)
                if mutation == 'missing':
                    s.pop('_revision')
                elif mutation == 'duplicate':
                    s['reviews'].append(copy.deepcopy(s['reviews'][0]))
                elif mutation == 'unknown':
                    s['reviews'][0]['id'] = 999999
                elif mutation == 'incomplete':
                    s.pop('decisions')
                elif mutation == 'malformed':
                    s['reviews'] = ['invalid row']
                else:
                    s['reviews'][0]['thought'] = {'not': 'a sqlite value'}
                with self.assertRaises(Problem):
                    self.save(s)
                self.assertEqual(dashboard.load_state(), state)

    def test_deleted_identity_is_not_reused_and_server_returns_allocated_ids(self):
        s = self.seeded()
        old_id = s['reviews'][0]['id']
        s['reviews'] = []
        self.save(s)
        s = dashboard.load_state()
        s['reviews'] = [{'thought': 'new', '_client_id': 'draft-new'}]
        response = self.save(s)
        self.assertGreater(response['state']['reviews'][0]['id'], old_id)
        self.assertEqual(response['assigned_ids']['reviews']['draft-new'], response['state']['reviews'][0]['id'])

    def test_api_rejects_old_client_and_returns_structured_conflict(self):
        # Only mount the two handlers, never start dashboard.app's real lifespan.
        api = FastAPI()
        api.get('/api/data')(dashboard.get_data)
        api.put('/api/data')(dashboard.put_data)
        with TestClient(api, headers={'X-Legacy-State-Protocol': '1'}) as client:
            response = client.get('/api/data')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            s = response.json()
            # Old HTML can echo the new revision while still dropping row IDs.
            outdated = client.put('/api/data', json=s, headers={'X-Legacy-State-Protocol': '0'})
            self.assertEqual(outdated.status_code, 409)
            self.assertEqual(outdated.json()['code'], 'client_outdated')
            old = copy.deepcopy(s)
            s['todos'] = [{'id': 'todo', 'date': '2026-10-16', 'title': 'keep', 'done': False}]
            r = client.put('/api/data', json=s)
            self.assertEqual(r.status_code, 200)
            self.assertIn('_revision', r.json()['state'])
            r = client.put('/api/data', json=old)
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json()['code'], 'state_conflict')
            old.pop('_revision')
            self.assertEqual(client.put('/api/data', json=old).status_code, 409)


if __name__ == '__main__':
    unittest.main()
