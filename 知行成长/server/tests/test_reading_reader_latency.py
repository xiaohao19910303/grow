"""Reader setup and article metadata avoid unrelated history and cloud reads."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_legacy_cloud_api import CloudHTTPFixture


class ReaderLatencyTests(CloudHTTPFixture):
    def test_setup_does_not_load_articles_jobs_or_sources(self):
        with (patch.object(self.reader,'articles',side_effect=AssertionError('article history')),
             patch.object(self.reader,'jobs',side_effect=AssertionError('job history')),
             patch.object(self.reader,'all_sources',side_effect=AssertionError('source history')),
             TestClient(self.app,base_url='http://localhost') as client):
            response=client.get('/api/reading/setup')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(set(response.json()),{'preferences','topics'})

    def test_reader_batches_metadata_and_uses_saved_body_and_guide(self):
        self.reader.save_full_text(self.aid,'Saved full body. '*30)
        # Old PDF records must not break the filtered latest-body-job lookup.
        self.reader.put('reading_records','old-pdf',{'id':'old-pdf','type':'job','kind':'collect','state':'failed','raw':'pdf\x00stream'})
        with (patch.object(self.reader,'conn',wraps=self.reader.conn) as connections,
             patch.object(self.reader,'jobs',side_effect=AssertionError('unrelated job history')),
             patch.object(self.reader.documents.content,'read_text',side_effect=AssertionError('unnecessary GitHub read'))):
            detail=self.reader.article_detail(self.aid)
        self.assertEqual(connections.call_count,2)
        self.assertIn('Saved full body.',detail['full_text'])
        self.assertEqual(detail['note']['text'],'PRIVATE READING NOTE')
        self.assertFalse(detail['content_needs_refresh'])
        self.assertNotIn('context',detail.get('content_job') or {})

    def test_reader_returns_most_recent_body_job_only(self):
        for jid,kind,aid,date in [('older','fetch_full',self.aid,'2026-10-16'),('latest','fetch_full',self.aid,'2026-10-17'),('other','guide',self.aid,'2026-10-18')]:
            self.reader.put('reading_records','job-'+jid,{'id':'job-'+jid,'type':'job','kind':kind,'state':'failed','created_at':date,'context':{'article_id':aid},'request':'private'})
        detail=self.reader.article_detail(self.aid)
        self.assertEqual(detail['content_job']['id'],'job-latest')
        self.assertNotIn('context',detail['content_job'])
        self.assertNotIn('request',detail['content_job'])
