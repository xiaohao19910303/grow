"""Stable knowledge identities, HTTP contracts and additive tenant migrations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2

import db
from knowledge.api import register
from platform_schema import TABLES
from test_legacy_cloud_schema import PostgreSQLFixture


class KnowledgeStableIDTests(PostgreSQLFixture):
    def setUp(self):
        self.real_connect = db.connect
        super().setUp()
        with db.connect() as c:
            c.executescript(TABLES)
        self.app = FastAPI()
        self.store = register(self.app, Path('/unused'), Path('/unused'))
        self.store.initialize()
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.body = dict(name='贝叶斯更新', category='认知', summary='根据证据更新判断',
                         source='教材', kind='concept', date='2026-10-25',
                         source_path='教材/判断.md', source_hash='version-1')

    def upsert(self, **updates):
        return self.client.post('/api/knowledge/upsert', json=self.body | updates)

    def node(self, **updates):
        response = self.upsert(**updates)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['knowledge']

    def test_http_import_lookup_and_graph_share_identity(self):
        node = self.node()
        uuid.UUID(node['stable_id'])
        result = self.client.get('/api/knowledge/by-stable-id/' + node['stable_id'])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), node)
        graph = self.client.get('/api/knowledge/graph').json()
        self.assertEqual(graph['nodes'][0]['stable_id'], node['stable_id'])

    def test_repeat_and_changed_hash_preserve_identity_and_links(self):
        first = self.node()
        other = self.node(name='反证')
        self.store.save_links([(first['id'], other['id'], 'related', 3)])
        repeated = self.node()
        changed = self.node(source_hash='version-2', summary='更新后的理解')
        self.assertEqual((first['id'], first['stable_id']), (repeated['id'], repeated['stable_id']))
        self.assertEqual((first['id'], first['stable_id']), (changed['id'], changed['stable_id']))
        self.assertEqual(changed['summary'], '更新后的理解')
        self.assertEqual(self.store.get_stats()['total_nodes'], 2)
        self.assertEqual(self.store.get_stats()['total_links'], 1)

    def test_one_file_can_contain_multiple_nodes_and_kinds(self):
        nodes = [self.node(), self.node(name='反证'), self.node(kind='tool'),
                 self.node(source_path='另一份教材.md')]
        self.assertEqual(len({n['stable_id'] for n in nodes}), 4)

    def test_concurrent_imports_create_one_identity(self):
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.upsert(), range(8)))
        self.assertEqual([r.status_code for r in results], [200] * 8)
        self.assertEqual(len({r.json()['knowledge']['stable_id'] for r in results}), 1)
        self.assertEqual(self.store.get_stats()['total_nodes'], 1)

    def test_legacy_backfill_and_repeated_initialization_preserve_ids_and_links(self):
        with db.connect() as c:
            c.execute('ALTER TABLE knowledge ALTER COLUMN stable_id DROP NOT NULL')
            old = c.execute("INSERT INTO knowledge(name,source,kind,stable_id) VALUES ('旧知识','旧教材','concept',NULL) RETURNING id").fetchone()[0]
            other = c.execute("INSERT INTO knowledge(name) VALUES ('关联节点') RETURNING id").fetchone()[0]
        self.store.save_links([(old, other, 'related', 2)])
        self.store.initialize()
        graph = self.store.get_graph()
        before = {n['id']: n['stable_id'] for n in graph['nodes']}
        self.store.initialize()
        self.assertEqual(before, {n['id']: n['stable_id'] for n in self.store.get_graph()['nodes']})
        self.assertEqual(graph['links'][0]['source_id'], old)

    def test_import_reuses_matching_legacy_node_without_losing_links(self):
        with db.connect() as c:
            old = c.execute('INSERT INTO knowledge(name,source,kind) VALUES (?,?,?) RETURNING id',
                            (self.body['name'], self.body['source'], self.body['kind'])).fetchone()[0]
        imported = self.node()
        self.assertEqual(imported['id'], old)
        self.assertEqual(self.store.get_stats()['total_nodes'], 1)

    def test_ambiguous_legacy_matches_are_not_silently_merged(self):
        with db.connect() as c:
            for _ in range(2):
                c.execute('INSERT INTO knowledge(name,source,kind) VALUES (?,?,?)',
                          (self.body['name'], self.body['source'], self.body['kind']))
        response = self.upsert()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.store.get_stats()['total_nodes'], 2)

    def test_related_nodes_are_unique_ranked_and_support_both_directions(self):
        origin = self.node()
        high = self.node(name='高权重')
        low = self.node(name='低权重')
        self.store.save_links([(high['id'], origin['id'], 'related', 4),
                               (origin['id'], high['id'], 'keyword', 2),
                               (origin['id'], low['id'], 'related', 1)])
        response = self.client.get('/api/knowledge/by-stable-id/' + origin['stable_id'] + '/related')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([n['id'] for n in response.json()['related']], [high['id'], low['id']])
        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(self.client.get('/api/knowledge/by-stable-id/' + origin['stable_id'] + '/related?limit=1').json()['count'], 1)

    def test_unknown_nodes_and_invalid_limits_have_client_errors(self):
        url = '/api/knowledge/by-stable-id/' + str(uuid.uuid4())
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url + '/related').status_code, 404)
        self.assertEqual(self.client.get(url + '/related?limit=0').status_code, 400)

    def test_invalid_imports_are_rejected_without_creating_nodes(self):
        for update in ({'source_path': ''}, {'source_hash': []}, {'name': '  '},
                       {'stable_id': 'client-chosen'}, {'summary': {}}, {'name': 'x' * 501}):
            with self.subTest(update=update):
                self.assertEqual(self.upsert(**update).status_code, 422)
        self.assertEqual(self.store.get_stats()['total_nodes'], 0)

    def test_storage_failure_is_sanitized(self):
        with patch.object(self.store, 'upsert_knowledge', side_effect=psycopg2.OperationalError('PRIVATE DATABASE SECRET')):
            response = self.upsert()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn('PRIVATE DATABASE SECRET', response.text)

    def test_completed_legacy_migration_also_upgrades_stable_columns(self):
        from legacy_schema import migrate
        migrate()
        with db.connect() as c:
            c.execute('ALTER TABLE knowledge DROP COLUMN stable_id CASCADE')
        migrate()
        with db.connect() as c:
            node = c.execute("INSERT INTO knowledge(name) VALUES ('后续新节点') RETURNING stable_id").fetchone()
        uuid.UUID(node[0])

    def test_verification_is_schema_scoped_and_read_only(self):
        from migrate_knowledge_stable_ids import verify_migration
        other = 'knowledge_other_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:
            c.cursor().execute('CREATE SCHEMA ' + other)
            c.cursor().execute('CREATE TABLE ' + other + '.knowledge(id SERIAL PRIMARY KEY,name TEXT)')
        try:
            self.assertTrue(verify_migration())
            with patch('db.connect', lambda *a, **kw: self.real_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                self.assertFalse(verify_migration())
                with db.connect() as c:
                    columns = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='knowledge'")]
                self.assertNotIn('stable_id', columns)
        finally:
            with psycopg2.connect(self.dsn) as c:
                c.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')

    def test_same_source_and_guessed_id_cannot_cross_tenants(self):
        first = self.node()
        other = 'knowledge_tenant_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:
            c.cursor().execute('CREATE SCHEMA ' + other)
        try:
            with patch('db.connect', lambda *a, **kw: self.real_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                with db.connect() as c:
                    c.executescript(TABLES)
                self.store.initialize()
                self.assertEqual(self.client.get('/api/knowledge/by-stable-id/' + first['stable_id']).status_code, 404)
                self.assertEqual(self.client.get('/api/knowledge/by-stable-id/' + first['stable_id'] + '/related').status_code, 404)
                second = self.node()
                self.assertNotEqual(first['stable_id'], second['stable_id'])
                self.assertEqual(self.store.get_stats()['total_nodes'], 1)
            self.assertEqual(self.store.get_stats()['total_nodes'], 1)
        finally:
            with psycopg2.connect(self.dsn) as c:
                c.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')
