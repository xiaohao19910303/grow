"""I4 real source/Zook/PG protocol: shared H5 drafts, CAS, replay and explicit finish."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import httpx
import mobile_library
import mobile_private
import study_notes
import study_materials
import test_mobile_execution_http as fixture
from test_plans import B,D,S,content


class PrivateLearningHTTPTests(fixture.MobileExecutionHTTPTests):
    def test_private_learning_source_cas_response_loss_completion_versions_and_revoke(self):
        study_materials.initialize();study_notes.register(self.app)
        folder=self.root/'英文阅读'/'每日文章';folder.mkdir(parents=True,exist_ok=True)
        body='# Day001\n\n## 练习\n\n- Why read?\n- What changed?\n'
        (folder/'Day001.md').write_text(body);(folder/'Day002.md').write_text('# Day002\n\nRead the next course.')
        materials=study_materials.Materials(self.root);mobile_library.register(self.app,self.s,materials)
        draft=self.s.draft({'brief':B,'document':copy.deepcopy(D)});pid=self.s.adopt(draft['id'],'private-formal-adopt')['plan_id'];self.s.save_sources(pid,S);ctx=self.s.course_context(pid);draft=self.s.course_draft(ctx,content(ctx),'references');self.s.publish_course(draft['id'],'private-formal-publish')
        ticket=self.native('POST','action-link-tickets',{});p=self.web('mobile-learning/preview',{'code':ticket['code']});self.web('mobile-learning/connect',{'code':ticket['code'],'preview_id':p['preview_id'],'consent':True});mobile_library.sync(self.s,materials)
        courses=self.native('GET','learning-library')['lessons'];english=next(x for x in courses if x['collection_id']=='yingyu' and x['number']==1);formal=next(x for x in courses if x['collection_id']==pid)
        path='learning-library/'+english['id']+'/private';self.assertFalse(self.native('GET',path)['enabled'])
        bad=self.client.post('/api/mobile-learning/private-consent',json={'enabled':True,'consent':True});self.assertEqual(bad.status_code,403)
        self.web('mobile-learning/private-consent',{'enabled':True,'consent':True})
        raw=hashlib.sha256(body.encode()).hexdigest();draft=dict(notes='H5 private note',answers={'练习:1':'H5 answer'},version=raw,revision=0,key='private-h5-save-1')
        r=self.client.put('/api/study-notes/yingyu/Day001.md',json=draft,headers=self.headers);self.assertEqual(r.status_code,200,r.text)
        mobile_private.sync(self.s,materials);first=self.native('GET',path);self.assertEqual(first['state']['notes'],draft['notes']);self.assertEqual(first['state']['answers'][0]['id'],'练习:1');self.assertFalse(first['state']['completed']);self.assertIsNone(first['state']['completed_at'])
        def command(state,key,action='save',**values):return dict(id=key,content_version=state['content_version'],revision=state['revision'],action=action,notes=state['notes'],answers=state['answers'],position=state['position'],**values)
        queued=command(first['state'],'private-phone-save-1');queued['notes']='Phone input retained';self.native('POST',path,queued)
        # H5 writes while a phone command is pending. Neither client silently overwrites.
        self.client.put('/api/study-notes/yingyu/Day001.md',json={**draft,'revision':1,'key':'private-h5-save-2','notes':'H5 changed'},headers=self.headers)
        mobile_private.sync(self.s,materials);conflict=self.native('GET',path);self.assertEqual(conflict['operations'][-1]['status'],'conflict');self.assertEqual(conflict['state']['notes'],'H5 changed')
        newer=command(conflict['state'],'private-phone-save-2');newer['notes']='Phone after comparison';newer['answers'][0]['answer']='Phone answer'
        self.native('POST',path,newer);send=mobile_library.call
        def lost(source,payload):
            result=send(source,payload)
            if payload.get('action')=='learning-private' and payload.get('results'):raise RuntimeError('response lost after source and target commit')
            return result
        with patch('mobile_library.call',lost):
            with self.assertRaises(RuntimeError):mobile_private.sync(self.s,materials)
        mobile_private.sync(self.s,materials);saved=self.native('GET',path);self.assertEqual(saved['operations'][-1]['status'],'applied');self.assertEqual(saved['state']['notes'],newer['notes']);self.assertFalse(saved['state']['completed'])
        web=self.client.get('/api/study-notes/yingyu/Day001.md').json();self.assertEqual(web['notes'],newer['notes']);self.assertEqual(web['answers']['练习:1'],'Phone answer');self.assertEqual(web['revision'],3)
        position=command(saved['state'],'private-position-1','position');position['position']=2;self.native('POST',path,position);mobile_private.sync(self.s,materials);resume=self.native('GET',path);self.assertEqual(resume['state']['position'],2)
        finish=command(resume['state'],'private-finish-1','complete');self.native('POST',path,finish);self.assertFalse(self.native('GET',path)['state']['completed']);mobile_private.sync(self.s,materials);done=self.native('GET',path);self.assertTrue(done['state']['completed']);self.assertIsNotNone(done['state']['completed_at']);self.assertEqual(materials.record('yingyu','Day001.md')['time_spent_seconds'],0)
        self.native('POST',path,finish);mobile_private.sync(self.s,materials);self.assertEqual(materials.record('yingyu','Day001.md')['revision'],1)
        fpath='learning-library/'+formal['id']+'/private';fs=self.native('GET',fpath)['state'];self.native('POST',fpath,command(fs,'private-formal-finish-1','complete'))
        from action_handoff_coordinator import source_fence
        with patch('action_handoff_coordinator.source_fence',side_effect=source_fence) as fence:
            mobile_private.sync(self.s,materials)
            self.assertEqual(fence.call_count,1,'Private source confirmation must not reacquire the shared fence on another session')
        self.assertTrue(self.native('GET',fpath)['state']['completed']);self.assertEqual(self.s.lessons(pid)[0]['learning_state'],'completed')
        (folder/'Day001.md').write_text(body+'\n\n## 新题练习\n\n- Explain a new idea.\n');mobile_library.sync(self.s,materials);mobile_private.sync(self.s,materials);changed=self.native('GET',path)['state'];self.assertNotEqual(changed['content_version'],changed['draft_version']);self.assertTrue(any(x['answer']=='Phone answer' for x in changed['answers']));self.assertEqual(changed['position'],0)
        self.web('mobile-learning/private-consent',{'enabled':False,'consent':True});mobile_private.sync(self.s,materials);self.assertFalse(self.native('GET',path)['enabled']);self.assertEqual(self.client.get('/api/study-notes/yingyu/Day001.md').json()['notes'],newer['notes'])
        self.assertEqual(self.native('GET','action-plans')['plans'],[])
        other=httpx.get(self.url+'/api/v1/lighttick/'+path,headers={'Authorization':'Bearer '+self.owners[1]['token']});self.assertEqual(other.status_code,403)
