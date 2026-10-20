"""Month hierarchy, private retrospectives and opt-in AI with a mocked provider."""
import hashlib
import json
from unittest.mock import patch, AsyncMock

import db
import action_plans as actions
import action_reviews as reviews
import test_action_plans as plan_tests


class ActionReviewTests(plan_tests.ActionPlansTests):
    def scope(self, plan, **updates):
        return dict(plan_id=plan['id'],start_date=plan['start_date'],end_date=plan['end_date']) | updates

    def post(self,path,body):
        return self.client.post('/api/action-plans/reviews'+path,json=body,headers=self.headers)

    def test_month_long_short_and_four_level_progress(self):
        year=self.create(period='year',start_date='2026-01-01',end_date='2026-12-31')
        month=self.create(period='month',start_date='2026-10-01',end_date='2026-10-31',parent_id=year['id'],horizon='long')
        week=self.create(period='week',start_date='2026-10-12',end_date='2026-10-18',parent_id=month['id'])
        day=self.create(parent_id=week['id'])
        self.assertEqual(month['horizon'],'long');self.assertEqual(day['horizon'],'short')
        start=self.change(day,'start').json()
        self.change(start['plan'],'finish',execution_id=start['execution']['id'],actual_minutes=20,note='EXPLICIT EXECUTION NOTE')
        parents=self.client.get('/api/action-plans').json()['plans']
        self.assertTrue(all(p['progress']['completed']==1 for p in parents))
        preview=self.post('/preview',self.scope(year)).json()
        self.assertEqual(preview['stats']['minutes'],20)
        self.assertEqual(preview['stats']['completed_days'],1)
        self.assertNotIn('EXPLICIT EXECUTION NOTE',json.dumps(preview))
        body=self.scope(year)|dict(key='manual-review-key',worked='先读书再看视频',obstacles='睡前分心',next_action='调整到晚饭后')
        first=self.post('',body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json(),self.post('',body).json())
        self.assertEqual(self.post('',body|dict(worked='修改')).status_code,409)
        history=self.client.get('/api/action-plans/reviews',params={'plan_id':year['id']}).json()
        self.assertEqual(history['review_total'],1)
        self.assertEqual(history['reviews'][0]['stats']['completed'],1)
        self.assertEqual(self.post('/preview',self.scope(month,end_date='2026-11-01')).status_code,422)
        invalid=dict(title='invalid',period='month',start_date='2026-10-01',end_date='2026-11-01',key='invalid-month-key')
        self.assertEqual(self.client.post('/api/action-plans',json=invalid,headers=self.headers).status_code,422)

    def test_ai_consent_exact_preview_credentials_privacy_and_retry(self):
        day=self.create()
        started=self.change(day,'start').json()
        self.change(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=5,note='PRIVATE EXECUTION NOTE')
        self.post('',self.scope(day)|dict(key='review-before-ai',worked='PRIVATE MANUAL REVIEW'))
        scope=self.scope(day)
        preview=self.post('/preview',scope).json()
        cfg=dict(api_base_url='https://provider.example/v1',api_key='SECRET_FOR_TEST_ONLY',model_name='test-model')
        body=scope|dict(key='summary-retry-key',consent=True,snapshot_hash=preview['snapshot_hash'],ai_config=cfg)
        self.assertEqual(self.post('/generate',body|dict(consent=False)).status_code,422)
        self.assertEqual(self.post('/generate',body|dict(ai_config={})).status_code,422)
        generate=AsyncMock(return_value='进展总结：起步一次，实际5分钟。建议晚饭后先读5分钟。')
        with patch('action_reviews.generate_text',generate):
            result=self.post('/generate',body)
            self.assertEqual(result.status_code,202,result.text)
            self.assertEqual(self.post('/generate',body).status_code,202)
        self.assertEqual(generate.await_count,1)
        sent=generate.await_args.args[0]
        self.assertNotIn('PRIVATE EXECUTION NOTE',json.dumps(sent))
        self.assertNotIn('PRIVATE MANUAL REVIEW',json.dumps(sent))
        with db.connect() as c:
            stored=''.join(r[0] for r in c.execute('SELECT data FROM action_reports'))+''.join(r[0] for r in c.execute('SELECT result FROM action_operations'))
            self.assertNotIn(cfg['api_key'],stored)
        history=self.client.get('/api/action-plans/reviews',params={'plan_id':day['id']}).json()
        self.assertEqual(history['reports'][0]['state'],'ready')
        self.assertNotIn('snapshot',history['reports'][0]);self.assertNotIn('worker',history['reports'][0])
        selected=self.scope(day,include_notes=True,include_review=True)
        selected_preview=self.post('/preview',selected).json()
        self.assertIn('PRIVATE EXECUTION NOTE',json.dumps(selected_preview))
        self.assertIn('PRIVATE MANUAL REVIEW',json.dumps(selected_preview))
        with patch('action_reviews.generate_text',generate):
            self.assertEqual(self.post('/generate',selected|dict(key='selected-data-key',consent=True,snapshot_hash=selected_preview['snapshot_hash'],ai_config=cfg)).status_code,202)
        self.assertIn('PRIVATE EXECUTION NOTE',json.dumps(generate.await_args.args[0]))

    def test_changed_context_rejected_failed_generation_and_restart_recovery(self):
        plan=self.create()
        scope=self.scope(plan)
        preview=self.post('/preview',scope).json()
        cfg=dict(api_base_url='https://provider.example/v1',api_key='SECRET_FOR_TEST_ONLY',model_name='test')
        body=scope|dict(key='context-change-key',consent=True,snapshot_hash=preview['snapshot_hash'],ai_config=cfg)
        started=self.change(plan,'start').json()
        self.assertEqual(self.post('/generate',body).status_code,409)
        body.update(snapshot_hash=self.post('/preview',scope).json()['snapshot_hash'],key='failed-summary-key')
        with patch('action_reviews.generate_text',AsyncMock(side_effect=RuntimeError('raw-provider-secret'))):
            self.assertEqual(self.post('/generate',body).status_code,202)
        result=self.client.get('/api/action-plans/reviews',params={'plan_id':plan['id']}).json()
        self.assertEqual(result['reports'][0]['state'],'failed')
        self.assertNotIn('raw-provider-secret',json.dumps(result))
        with db.connect() as c:
            row=c.execute('SELECT id,data FROM action_reports').fetchone()
            report=json.loads(row[1]);report.update(worker='prior-process',state='generating')
            c.execute("UPDATE action_reports SET state='generating',data=? WHERE id=?",(actions.encoded(report),row[0]))
        result=self.client.get('/api/action-plans/reviews',params={'plan_id':plan['id']}).json()
        self.assertEqual(result['reports'][0]['state'],'failed')
        self.assertEqual(self.client.get('/api/action-plans').json()['execution']['id'],started['execution']['id'])

    def test_reviews_are_isolated_and_additive_schema_upgrade(self):
        plan=self.create()
        self.post('',self.scope(plan)|dict(key='private-review-key',worked='PRIVATE REVIEW'))
        with db.connect() as c:
            c.execute('DROP TABLE action_reports');c.execute('DROP TABLE action_reviews')
        # Simulate an account initialized by the earlier action-plans version.
        self.assertEqual(self.client.get('/api/action-plans').status_code,200)
        self.assertEqual(self.post('',self.scope(plan)|dict(key='after-upgrade-key',worked='upgraded')).status_code,200)
        import psycopg2,uuid
        other='reviews_other_'+uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('CREATE SCHEMA '+other)
        try:
            with patch('db.connect',lambda *a,**kw:self.raw_connect(self.dsn+' options=-csearch_path='+other,tenant=False)):
                self.assertEqual(self.client.get('/api/action-plans/reviews',params={'plan_id':plan['id']}).status_code,404)
                self.assertEqual(self.post('/preview',self.scope(plan)).status_code,404)
        finally:
            with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+other+' CASCADE')

    def test_review_context_caps_text_but_retains_all_fact_totals(self):
        plan=self.create()
        with db.connect() as c:
            for i in range(31):
                record=dict(id=f'execution-{i:03}',plan_id=plan['id'],title='执行',business_date='2026-10-18',timezone='Asia/Shanghai',started_at='2026-10-18T12:00:00+00:00',actual_minutes=2,outcome='interrupted',note='长'*500)
                c.execute("INSERT INTO action_executions VALUES (?,?,'interrupted',?)",(record['id'],plan['id'],actions.encoded(record)))
        preview=self.post('/preview',self.scope(plan,include_notes=True)).json()
        self.assertEqual(preview['stats']['minutes'],62)
        self.assertEqual(preview['stats']['interrupted'],31)
        self.assertEqual(len(preview['records']),30)
        self.assertTrue(preview['records_truncated'])
        self.assertTrue(all(len(r['note'])<320 and r['note'].endswith('（已截取）') for r in preview['records']))

    def test_summary_transport_collects_only_validated_provider_content(self):
        import asyncio
        async def transport(messages,cfg):
            self.assertIn('不推断刷短视频时长',messages[0]['content'])
            yield {'text':'进展总结：'}
            yield {'usage':{'total_tokens':10}}
            yield {'text':'已起步一次。'}
            yield {'done':True}
        with patch('copilot.transport.qwen_stream',transport):
            text=asyncio.run(reviews.generate_text({'stats':{'minimum':1}},{'key':'test-only'}))
        self.assertEqual(text,'进展总结：已起步一次。')
