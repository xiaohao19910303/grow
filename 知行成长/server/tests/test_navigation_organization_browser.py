"""Real browser navigation against private synthetic records; no business services."""
import functools
import json
import os
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from zoneinfo import ZoneInfo


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome')
class NavigationOrganizationBrowser(unittest.TestCase):
    def test_relocated_entries_keep_history_and_course_tools(self):
        from playwright.sync_api import sync_playwright, expect

        static = Path(__file__).resolve().parents[1] / 'static'

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.path = self.path.removeprefix('/static')
                super().do_GET()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(static)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        day = stamp[:10]
        legacy = dict(modules=[{'id': 'renzhi', 'name': '认知与通识', 'color': '#4F6EF7'}],
                      checkins={day: {'renzhi': 3}}, habits={day: {'minutes': 35, 'note': '保留时长备注'}},
                      customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[],
                      insights=[], todos=[], _revision='fixture')
        summary = {'id': 1, 'content': '原有课程总结内容', 'scope': 'full_course', 'created_at': stamp}
        flags = {'archived': True, 'completed': False}
        writes, errors = [], []
        job = {'id': 'summary-job', 'kind': 'summary', 'state': 'ready',
               'raw': '浏览器配置生成的总结', 'result_id': 1}

        def fixture(route):
            request = route.request
            path = request.url.split(base)[-1].split('?')[0]
            if request.method != 'GET':
                writes.append((request.method, path))
            if path == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': False}}
            elif path == '/api/data':
                if request.method == 'PUT':
                    legacy.update(request.post_data_json)
                    result = {'state': legacy, 'assigned_ids': {}}
                else:
                    result = legacy
            elif path == '/api/action-plans':
                result = {'plans': [], 'execution': None, 'server_time': stamp}
            elif path == '/api/action-plans/records':
                result = {'total': 1, 'records': [{'title': '原有执行记录', 'business_date': day,
                          'outcome': 'completed', 'actual_minutes': 20, 'note': '保留执行收获'}]}
            elif path == '/api/copilot/lessons/archived':
                result = {'items': [{'lesson_no': 1, 'completed_at': stamp, 'key_learnings': '原有归档收获',
                                    'mastery_level': 'fully_understood'}] if flags['archived'] else []}
            elif path == '/api/copilot/lessons/1/unarchive':
                flags['archived'] = False
                result = {'ok': True}
            elif path == '/api/copilot/lessons':
                result = {'items': [{'lesson_no': 1}] if flags['completed'] else []}
            elif path == '/api/copilot/summaries':
                result = {'items': [summary]}
            elif path == '/api/copilot/summaries/1':
                result = summary
            elif path == '/api/copilot/summaries/generate':
                self.assertEqual(request.post_data_json['ai_config']['api_key'], 'TEST_ONLY_BROWSER_KEY')
                summary['content'] = job['raw']
                result = job
            elif path == '/api/copilot/background-jobs/summary-job':
                result = job
            else:
                result = dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[],
                              entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[], checkins={})
            route.fulfill(body=json.dumps(result), content_type='application/json')

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv(
                    'CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960}, timezone_id='Asia/Shanghai')
                    page.route('**/api/**', fixture)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    nav = page.locator('#subnav')
                    group = lambda key: page.locator(f'[data-group="{key}"]').click()
                    group('learning')
                    expect(nav).not_to_contain_text('学习打卡')
                    expect(nav).not_to_contain_text('课程归档')
                    expect(nav).not_to_contain_text('课程总结')
                    tools = page.get_by_role('group', name='认知与通识课程工具')
                    tools.get_by_role('button', name='课程归档', exact=True).click()
                    expect(page.locator('#archiveRoot')).to_contain_text('原有归档收获')
                    expect(nav.locator('[aria-current="page"]')).to_have_text('我的课程')
                    expect(page.locator('[data-group="learning"]')).to_have_attribute('aria-current', 'page')
                    page.locator('#view-archive').get_by_role('button', name='返回我的课程').click()
                    tools.get_by_role('button', name='课程总结', exact=True).click()
                    expect(page.locator('#summaryList')).to_contain_text('原有课程总结内容')
                    expect(page.locator('#summaryRoot')).to_contain_text('暂无已完成课程')
                    page.locator('#summaryList [data-action="view"]').click()
                    expect(page.locator('#outputContent')).to_have_text('原有课程总结内容')
                    page.locator('#view-summary').get_by_role('button', name='返回我的课程').click()
                    flags['completed'] = True
                    tools.get_by_role('button', name='课程总结', exact=True).click()
                    expect(page.get_by_role('button', name='生成整课总结', exact=True)).to_be_visible()
                    page.get_by_role('button', name='设置', exact=True).click()
                    page.locator('#apiBaseUrl').fill('https://model.example/v1')
                    page.locator('#apiKey').fill('TEST_ONLY_BROWSER_KEY')
                    page.locator('#modelName').fill('test-model')
                    page.get_by_role('button', name='保存配置', exact=True).click()
                    group('learning')
                    tools.get_by_role('button', name='课程总结', exact=True).click()
                    page.get_by_role('button', name='生成整课总结', exact=True).click()
                    expect(page.locator('#outputContent')).to_have_text('浏览器配置生成的总结')
                    group('growth')
                    nav.get_by_role('button', name='学习历史', exact=True).click()
                    page.locator('#contextnav').get_by_role('button', name='学习足迹', exact=True).click()
                    expect(page.locator('#todayChips')).to_contain_text('已完成')
                    expect(page.locator('#matrix').get_by_text('✓', exact=True)).to_have_count(1)
                    shots = Path(os.getenv('NAV_SCREENSHOT_DIR', '/tmp/grow-navigation-verification'))
                    shots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / 'growth-desktop.png'), full_page=True)
                    nav.get_by_role('button', name='学习历史', exact=True).click()
                    page.locator('#contextnav').get_by_role('button', name='补记时长', exact=True).click()
                    expect(page.locator('#habitMinutes')).to_have_value('35')
                    expect(page.locator('#habitNote')).to_have_value('保留时长备注')
                    page.locator('#habitMinutes').fill('40')
                    page.get_by_role('button', name='保存当天记录', exact=True).click()
                    expect(page.locator('#storageStatus')).to_contain_text('已保存')
                    self.assertEqual(legacy['habits'][day]['minutes'], 40)
                    self.assertEqual(legacy['checkins'][day]['renzhi'], 3)
                    group('records')
                    expect(nav).not_to_contain_text('学习时长')
                    expect(nav).not_to_contain_text('执行记录')
                    group('actions')
                    nav.get_by_role('button', name='执行记录', exact=True).click()
                    expect(page.locator('#view-action-records')).to_contain_text('原有执行记录')
                    expect(page.locator('#view-action-records')).to_contain_text('保留执行收获')
                    group('learning')
                    expect(page.locator('#view-library')).to_be_visible()
                    tools.get_by_role('button', name='课程归档', exact=True).click()
                    page.locator('#archiveRoot [data-action="unarchive"]').click()
                    expect(page.locator('#archiveRoot')).to_contain_text('暂无归档课程')
                    self.assertFalse(flags['archived'])
                    page.locator('#view-archive').get_by_role('button', name='返回我的课程').click()
                    for width in (320, 768, 1024, 1440):
                        page.set_viewport_size({'width': width, 'height': 960})
                        for destination in ('learning', 'actions', 'growth'):
                            group(destination)
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    group('learning')
                    page.screenshot(path=str(shots / 'courses-mobile.png'), full_page=True)
                    page.reload()
                    group('growth')
                    nav.get_by_role('button', name='学习历史', exact=True).click()
                    page.locator('#contextnav').get_by_role('button', name='补记时长', exact=True).click()
                    expect(page.locator('#habitMinutes')).to_have_value('40')
                    self.assertEqual(errors, [])
                    self.assertEqual(writes, [('POST', '/api/copilot/summaries/generate'), ('PUT', '/api/data'),
                                              ('POST', '/api/copilot/lessons/1/unarchive')])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
