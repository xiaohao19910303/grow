"""Review real feedback, reconcile a parent change and recover a committed follow-up."""
import json,os,select,subprocess,sys,tempfile,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Explicit isolated browser opt-in')
class PracticeFollowUpBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_learning_practice_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);cls.addClassCleanup(cls.stop)
        if not select.select([cls.proc.stdout],[],[],60)[0]:raise RuntimeError('Follow-up fixture startup timed out')
        line=cls.proc.stdout.readline()
        if not line:raise RuntimeError(cls.proc.stderr.read())
        cls.fixture=json.loads(line);cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');cls.addClassCleanup(cls.browser.close)
    @classmethod
    def stop(cls):
        cls.proc.terminate()
        try:cls.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:cls.proc.kill();cls.proc.wait(timeout=5)
        cls.proc.stdout.close();cls.proc.stderr.close()
    def test_parent_conflict_original_retry_and_origin_survive_reload(self):
        context=self.browser.new_context(viewport={'width':1280,'height':1100});self.addCleanup(context.close)
        base=self.fixture['url'];headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        def post(path,body):
            r=context.request.post(base+'/api/action-plans'+path,data=body,headers=headers);self.assertEqual(r.status,200,r.text());return r.json()
        lesson=context.request.get(base+'/api/learning-practices/source?module_id=yingyu&filename=Day001.md').json()['source']
        p=post('/practices',{'key':'browser-origin-create','title':'Original report','source_kind':'lesson','source_id':lesson['id'],'source_version':lesson['version'],'date':None,'timezone':'Asia/Shanghai'})['plan']
        p=post('/'+p['id']+'/operations',{'key':'browser-origin-feedback','revision':p['revision'],'action':'practice-feedback','feedback':{'outcome':'unknown','result':'Tried the first report','next_step':'Ask a colleague'}})['plan']
        parent=post('',{'key':'browser-followup-parent','title':'Next week','period':'week','start_date':'2026-11-02','end_date':'2026-11-08','timezone':'Asia/Shanghai','target_minutes':60})['plans'][0]
        fragment='#mobile/practice/'+p['id']+'/'+p['practice_feedback'][0]['id']
        page=context.new_page();page.set_default_timeout(15000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(base+'/'+fragment)
        title=page.get_by_label('下次准备实践什么',exact=True);expect(title).to_have_value('Ask a colleague')
        page.get_by_label('后续实践日期（留空暂不安排）',exact=True).fill('2026-11-03');page.get_by_label('后续实践上级计划',exact=True).select_option(parent['id'])
        fields={k:parent[k] for k in ('title','period','horizon','start_date','end_date','timezone','parent_id','target_minutes','minimum_minutes','estimated_minutes','target_count','at','reminder','reason','if_then','target','completion_mode')};fields['target_minutes']=30
        post('/'+parent['id']+'/operations',{'key':'browser-reduce-parent','revision':parent['revision'],'action':'edit','fields':fields})
        page.get_by_role('button',name='确认后续安排',exact=True).click();expect(page.get_by_role('status').filter(has_text='输入已保留')).to_be_visible();expect(title).to_have_value('Ask a colleague')
        page.get_by_role('button',name='读取最新来源并保留输入',exact=True).click();expect(page.get_by_text('使用该计划当前日期、时区与约束；其目标30分钟保持原值。整体预算或阶段重排请在原计划中审阅。',exact=True)).to_be_visible()
        context.request.post(base+'/fixture/drop-next');page.get_by_role('button',name='确认后续安排',exact=True).click();expect(title).to_be_disabled();expect(page.get_by_role('status').filter(has_text='输入已保留')).to_be_visible()
        self.assertEqual(len(context.request.get(base+'/api/action-plans/practices').json()['practices']),2,'verify target commit before withdrawing source')
        context.request.post(base+'/fixture/withdraw-reading')
        page.reload();expect(title).to_have_value('Ask a colleague');expect(title).to_be_disabled();page.get_by_role('button',name='重试原后续提交',exact=True).click()
        expect(page.get_by_text('后续实践已保存，原反馈与完成状态保持不变。',exact=True)).to_be_visible();expect(page.get_by_role('button',name='确认后续安排',exact=True)).to_have_count(0)
        workspace=context.request.get(base+'/api/action-plans').json();practices=[v for v in workspace['plans'] if v.get('practice_source')];self.assertEqual(len(practices),2)
        follow=next(v for v in practices if v.get('practice_origin'));self.assertEqual(follow['practice_origin'],{'plan_id':p['id'],'feedback_id':p['practice_feedback'][0]['id']})
        self.assertEqual(next(v for v in workspace['plans'] if v['id']==parent['id'])['target_minutes'],30);self.assertEqual(context.request.get(base+'/api/action-plans/records').json()['total'],0)
        page.set_viewport_size({'width':375,'height':900});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375);self.assertEqual(errors,[])
        out=Path(os.getenv('GROW_FOLLOWUP_BROWSER_EVIDENCE',tempfile.mkdtemp(prefix='grow-followup-browser-')));out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/'followup-recovered-mobile.png'),full_page=True)
