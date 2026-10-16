"""T04 checks: temporary database only; no application lifespan or real service."""
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as dashboard
from copilot.core import Problem
from fastapi import FastAPI
from fastapi.testclient import TestClient


class LegacyStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='grow-t04-')
        self.root = Path(self.tmp.name)
        self.patch = patch.object(dashboard, 'DB_PATH', self.root / 'data.db')
        self.patch.start()
        dashboard.init_db()
        dashboard.save_state({'modules': dashboard.DEFAULT_MODULES})

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

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
