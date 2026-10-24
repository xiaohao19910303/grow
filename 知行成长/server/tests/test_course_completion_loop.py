"""Course completion loop uses real routes, isolated PG and synthetic provider output."""
from fastapi.testclient import TestClient
from test_legacy_cloud_api import CloudHTTPFixture, OWN


class CourseCompletionLoop(CloudHTTPFixture):
    def setUp(self):
        super().setUp()
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1'}

    def post(self,path,payload):
        return self.client.post('/api/copilot'+path,json=payload,headers=self.headers)

    def complete(self):
        lesson=self.course.lesson(1)
        response=self.post('/lessons/1/complete',{'version':lesson['version'],'time_spent_seconds':60,'key':'loop-complete'})
        self.assertEqual(response.status_code,200,response.text)

    def test_complete_feedback_archive_unarchive_and_explicit_summary(self):
        self.complete()
        payload={'key':'loop-feedback','mastery_level':'basically_understood','value_rating':2,
                 'feeling_tags':['例子很好'],'key_learnings':'PRIVATE LOOP FEEDBACK'}
        response=self.post('/lessons/1/feedback',payload);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/copilot/lessons/1/feedback').json()['key_learnings'],payload['key_learnings'])
        response=self.post('/lessons/1/archive',{'key':'loop-archive'});self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(any(row['lesson_no']==1 for row in self.client.get('/api/copilot/lessons/archived').json()['items']))
        response=self.post('/lessons/1/unarchive',{'key':'loop-unarchive'});self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/copilot/lessons/archived').json()['items'],[])
        request={'scope':'full_course','key':'loop-summary'}
        self.assertEqual(self.post('/summaries/generate',request).status_code,422)
        response=self.post('/summaries/generate',{**request,'ai_config':OWN})
        self.assertEqual(response.status_code,200,response.text);self.assertIn('event: complete',response.text)
        self.assertNotIn(OWN['api_key'],str(self.client.get('/api/copilot/summaries').json()))

    def test_feedback_rejects_invalid_mastery_and_value(self):
        self.complete()
        for field,value in [('mastery_level','invalid_level'),('value_rating',5)]:
            payload={'key':'loop-invalid-'+field,'mastery_level':'basically_understood','value_rating':2,field:value}
            self.assertEqual(self.post('/lessons/1/feedback',payload).status_code,422)

    def test_archive_requires_a_completed_lesson(self):
        self.assertEqual(self.post('/lessons/1/archive',{'key':'loop-invalid-archive'}).status_code,409)
        self.assertEqual(self.client.get('/api/copilot/lessons/archived').json()['items'],[])
