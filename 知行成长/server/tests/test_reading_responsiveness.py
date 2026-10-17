"""Remote publication must never occupy the ASGI event loop."""
import threading
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_legacy_cloud_api import CloudHTTPFixture

class ReadingResponsiveness(CloudHTTPFixture):
    def test_slow_body_publication_keeps_health_and_job_polling_responsive(self):
        started=threading.Event();save=self.reader.save_full_text
        async def content(url):return 'Public readable body. '*30
        def slow(aid,text):
            started.set();time.sleep(1.5);return save(aid,text)
        @self.app.get('/health')
        async def health():return {'ok':True}
        with patch('reading.service.fetch_article_content',content),patch.object(self.reader,'save_full_text',side_effect=slow),TestClient(self.app,base_url='http://localhost') as client:
            r=client.post('/api/reading/articles/'+self.aid+'/fetch_full',json={'data':{'key':'responsive-body'}},headers={'X-Copilot-Request':'1'})
            self.assertEqual(r.status_code,200,r.text);jid=r.json()['id'];self.assertTrue(started.wait(timeout=10))
            then=time.monotonic();self.assertEqual(client.get('/health').status_code,200)
            self.assertLess(time.monotonic()-then,.6,'Publication blocked the event loop')
            self.assertEqual(client.get('/api/reading/jobs/'+jid).status_code,200)
            for _ in range(100):
                job=client.get('/api/reading/jobs/'+jid).json()
                if job['state'] not in ('queued','running'):break
                time.sleep(.03)
            self.assertEqual(job['state'],'ready',job)
            self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE READING NOTE')
