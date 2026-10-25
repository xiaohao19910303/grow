"""Production CSS: one source, status contrast, keyboard focus and motion preferences."""
import os
import unittest
from playwright.sync_api import expect
from test_setup_help_browser import SetupHelpBrowserTests as _Fixture

@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated Chrome')
class DesignTokensBrowserTests(unittest.TestCase):
    # Reuse only fixture lifecycle helpers, without inheriting its feature cases.
    setUpClass=classmethod(_Fixture.setUpClass.__func__)
    stop_fixture=classmethod(_Fixture.stop_fixture.__func__)
    setUp=_Fixture.setUp
    tearDown=_Fixture.tearDown

    def test_single_source_and_responsive_page(self):
        response=self.context.request.get(self.base+'/static/design-tokens.css')
        self.assertEqual(response.status,200);self.assertIn('--primary:',response.text())
        for width in (320,768,1440):
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
            self.page.screenshot(path=str(self.evidence/f'tokens-page-{width}.png'))
        inline=self.page.locator('head > style').first.text_content()
        self.assertNotRegex(inline,r'--(?:primary|bg|card|border|radius|green|red|amber)\s*:', 'Token definitions should have one production source')
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--green').trim()"),'#2FA84F')

    def test_status_text_contrast(self):
        self.page.evaluate("""() => {
          const box=document.createElement('section');box.id='contrastFixture';box.className='section';
          for(const [kind,text] of [['on','正常状态'],['warn','注意事项'],['err','连接异常']]){
            const badge=document.createElement('span');badge.className='badge '+kind;badge.textContent=text;box.append(badge);
          }
          document.querySelector('.wrap').prepend(box);
        }""")
        self.page.screenshot(path=str(self.evidence/'status-contrast.png'))
        ratios=self.page.locator('#contrastFixture .badge').evaluate_all("""nodes=>nodes.map(el=>{
          const s=getComputedStyle(el),lum=color=>{
            const c=color.match(/[\\d.]+/g).slice(0,3).map(x=>Number(x)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
            return .2126*c[0]+.7152*c[1]+.0722*c[2];
          };const a=lum(s.color),b=lum(s.backgroundColor);
          return {name:el.className,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
        })""")
        for row in ratios:self.assertGreaterEqual(row['ratio'],4.5,row)

    def test_keyboard_input_focus_and_reduced_motion(self):
        self.page.evaluate("goTab('settings')")
        field=self.page.get_by_label('API Base URL',exact=True);field.focus()
        self.page.keyboard.press('Shift+Tab');self.page.keyboard.press('Tab');expect(field).to_be_focused()
        style=field.evaluate("el=>{const s=getComputedStyle(el);return {style:s.outlineStyle,width:parseFloat(s.outlineWidth)};}")
        self.assertNotEqual(style['style'],'none');self.assertGreaterEqual(style['width'],2)
        self.page.screenshot(path=str(self.evidence/'keyboard-input-focus.png'))
        self.page.emulate_media(reduced_motion='reduce')
        button=self.page.get_by_role('button',name='开始配置引导',exact=True);button.scroll_into_view_if_needed();rect=button.bounding_box()
        self.page.mouse.move(rect['x']+rect['width']/2,rect['y']+rect['height']/2);self.page.mouse.down()
        try:
            motion=button.evaluate("el=>{const s=getComputedStyle(el);return {transform:s.transform,duration:parseFloat(s.transitionDuration)};}")
            self.assertEqual(motion['transform'],'none');self.assertLessEqual(motion['duration'],.001)
        finally:self.page.mouse.up()

del _Fixture
