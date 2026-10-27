import json
from pathlib import Path
import db
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.integration import create_action, overview, references,private_search
from search_service import SearchService
from timeline_service import TimelineService
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentIntegrationTests(PostgreSQLFixture):
    def test_metadata_discovery_and_explicit_action_are_private_and_idempotent(self):
        store=InvestmentStore();store.initialize()
        a=store.create('accounts',{'name':'PRIVATE AMOUNT 99000','opening_cash':'99000','baseline_date':'2026-10-26'},'a')
        review=store.create('reviews',{'account_id':a['id'],'date':'2026-10-28','text':'PRIVATE AMOUNT 99000',
            'next_experiment':'不自动外发'},'r')
        search=SearchService(Path('/unused')).search('投资',module_types=['investment'])
        self.assertEqual(search['total_count'],1)
        self.assertNotIn('99000',json.dumps(search))
        self.assertEqual(search['results'][0]['target']['id'],review['id'])
        self.assertEqual(SearchService(Path('/unused')).search('99000',module_types=['investment'])['total_count'],0)
        private=private_search(store,a['id'],'99000')
        self.assertEqual(private['total'],1);self.assertIn('99000',private['items'][0]['summary'])
        timeline=TimelineService(Path('/unused')).get_timeline('2026-10-26','2026-10-31',['investment'])
        self.assertNotIn('PRIVATE AMOUNT',json.dumps(timeline))
        body={'source_version':1,'title':'核对原始资料','date':'2026-10-29'}
        first=create_action(store,review['id'],body,'action-request')
        again=create_action(store,review['id'],body,'action-request-again')
        self.assertEqual(first['action_id'],again['action_id'])
        with db.connect() as c:
            rows=c.execute('SELECT data FROM action_plans').fetchall()
            self.assertEqual(len(rows),1);self.assertNotIn('99000',rows[0][0])
            action=json.loads(rows[0][0]);self.assertIsNone(action.get('target'))
            self.assertEqual(action['completion_mode'],'check')
        self.assertEqual(references(store,review['id'])['items'][0]['availability'],'available')
        self.assertTrue(overview(store,'2026-10-28')['metadata_only'])
        with db.connect() as c:c.execute('DELETE FROM action_plans WHERE id=?',(first['action_id'],))
        self.assertEqual(references(store,review['id'])['items'][0]['availability'],'unavailable')
        with self.assertRaises(Problem):create_action(store,'not-mine',body,'bad-source')
