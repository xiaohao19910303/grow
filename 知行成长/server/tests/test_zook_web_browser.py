"""Actual production login, explicit association and contextual re-entry in Chromium."""
import json,os,select,subprocess,sys,tempfile,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Explicit isolated browser opt-in')
class CanonicalWebBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_zook_web_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        cls.addClassCleanup(cls.stop)
        if not select.select([cls.proc.stdout],[],[],60)[0]:raise RuntimeError('Canonical web fixture startup timed out')
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
    def test_explicit_association_login_continuation_and_no_browser_tokens(self):
        context=self.browser.new_context(viewport={'width':1280,'height':1000});self.addCleanup(context.close)
        page=context.new_page();page.set_default_timeout(15000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        base=self.fixture['url'];fragment='#mobile/learn/'+self.fixture['lesson_id']
        page.goto(base+'/login'+fragment)
        page.locator('#username').fill('owner');page.locator('#password').fill(self.fixture['grow_password']);page.locator('#authSubmit').click()
        expect(page).to_have_url(base+'/'+fragment)
        page.goto(base+'/#view/settings')
        box=page.locator('#zookWebSettings');expect(box).to_be_visible()
        box.get_by_label('LightTick账号',exact=True).fill(self.fixture['account']);box.get_by_label('LightTick密码',exact=True).fill('Password1234')
        box.get_by_role('checkbox').check();box.get_by_role('button',name='验证并关联').click()
        expect(box.get_by_text('当前已使用LightTick账号登录，课程与记录仍按原授权范围接续。')).to_be_visible()
        self.assertEqual(context.request.get(base+'/api/auth/me').json()['auth_mode'],'zook')
        self.assertTrue(any(c['name']=='grow_zook_session' and c['httpOnly'] for c in context.cookies()))
        # Exit from the actual page and re-enter through the original lesson deep link.
        page.evaluate('Account.logout()');expect(page).to_have_url(base+'/login')
        page.goto(base+'/login'+fragment);page.get_by_role('button',name='LightTick账号',exact=True).click()
        page.locator('#username').fill(self.fixture['account']);page.locator('#password').fill('Password1234');page.locator('#authSubmit').click()
        expect(page).to_have_url(base+'/'+fragment)
        self.assertEqual(context.request.get(base+'/api/auth/me').json()['auth_mode'],'zook')
        browser_values=page.evaluate('JSON.stringify(Object.entries(localStorage))')
        self.assertNotIn('accessToken',browser_values);self.assertNotIn('refreshToken',browser_values);self.assertNotIn('Password1234',browser_values)
        self.assertEqual(errors,[])
        out=Path(os.getenv('GROW_C05_BROWSER_EVIDENCE',tempfile.mkdtemp(prefix='grow-c05-browser-')));out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/'canonical-login-lesson.png'),full_page=True)
