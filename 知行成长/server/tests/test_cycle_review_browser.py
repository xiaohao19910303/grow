"""Real browser checks for cycle reviews, timeline and the global search entry."""
import functools
import json
import os
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome')
class CycleReviewBrowser(unittest.TestCase):
    def test_navigation_preserves_reports_timeline_search_and_exports(self):
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
        reports = [{'id': 1, 'date': day, 'period_days': 30, 'content': '原有报告\n<img src=x onerror="throw Error(1)">'}]
        requests, writes, errors = [], [], []

        def fixture(route):
            request = route.request
            parsed = urlsplit(request.url)
            path, query = parsed.path, parse_qs(parsed.query)
            requests.append((path, query))
            if request.method != 'GET':
                writes.append((request.method, path))
            if path == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': False}}
            elif path == '/api/data':
                result = dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[],
                              decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            elif path == '/api/action-plans':
                result = {'plans': [], 'execution': None, 'server_time': stamp}
            elif path == '/api/behavior-report':
                result = reports
            elif path == '/api/behavior-report/generate':
                self.assertEqual(request.post_data_json['ai_config']['api_key'], 'TEST_ONLY')
                self.assertEqual(request.headers['x-copilot-request'], '1')
                reports.append({'id': 2, 'date': day, 'period_days': 30, 'content': '新生成的复盘报告'})
                result = reports[-1]
            elif path.startswith('/api/behavior-report/'):
                number = int(path.rsplit('/', 1)[-1])
                if request.method == 'DELETE':
                    self.assertEqual(request.headers['x-copilot-request'], '1')
                    reports[:] = [r for r in reports if r['id'] != number]
                    route.fulfill(status=204)
                    return
                result = next(r for r in reports if r['id'] == number)
            elif path == '/api/report':
                period = query.get('range', ['week'])[0]
                result = dict(range=period, start=day, end=day, days=7 if period == 'week' else 30,
                              active_days=2, total_minutes=70 if period == 'week' else 300, avg_minutes=10,
                              streak=2, decisions=1, predictions=1, reviews=1, insights=1, knowledge_count=1, modules=[])
            elif path in ('/api/timeline', '/api/search'):
                page = query.get('page', ['1'])[0]
                record = {'id': page, 'date': day, 'module': 'decision', 'title': '保留的历史记录' + page}
                result = {'records' if path.endswith('timeline') else 'results': [record], 'total_count': 51}
            elif path == '/api/timeline/stats':
                result = {'total_records': 51, 'active_days': 2}
            else:
                result = dict(modules=[], checkins={}, lessons=[], plans=[], records=[], items=[], articles=[],
                              jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[])
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
                    group = lambda key: page.locator(f'[data-group="{key}"]').click()
                    nav = page.locator('#subnav')
                    group('records')
                    nav.get_by_role('button', name='时间线', exact=True).click()
                    expect(page.locator('#timelineList')).to_contain_text('保留的历史记录1')
                    page.locator('#timelineTypeFilter').select_option('decision')
                    page.locator('#timelinePagination').get_by_role('button', name='下一页').click()
                    expect(page.locator('#timelineList')).to_contain_text('保留的历史记录2')
                    group('growth')
                    expect(nav).not_to_contain_text('时间线')
                    expect(nav).not_to_contain_text('搜索')
                    expect(nav.get_by_role('button', name='周报', exact=True)).to_have_count(0)
                    nav.get_by_role('button', name='周期复盘', exact=True).click()
                    expect(page.locator('#view-cycle-review')).to_be_visible()
                    expect(page.locator('#reportCards')).to_contain_text('1h 10m')
                    page.get_by_role('button', name='本月', exact=True).click()
                    expect(page.locator('#reportCards')).to_contain_text('5h 0m')
                    with page.expect_download() as download:
                        page.get_by_role('button', name='导出 Markdown 报告').click()
                    self.assertIn('report-month-', download.value.suggested_filename)
                    self.assertIn('# 月报', Path(download.value.path()).read_text())
                    page.locator('#contextnav').get_by_role('button', name='AI 报告', exact=True).click()
                    expect(nav.locator('[aria-current="page"]')).to_have_text('周期复盘')
                    expect(page.locator('#aiReportList')).to_contain_text('原有报告')
                    page.locator('#aiReportList').get_by_text('查看完整报告 →').click()
                    expect(page.locator('#modalBox')).to_contain_text('原有报告')
                    expect(page.locator('#modalBox img')).to_have_count(0)
                    page.locator('#modalBox').get_by_role('button', name='关闭').click()
                    page.get_by_role('button', name='设置', exact=True).click()
                    page.locator('#apiBaseUrl').fill('https://model.example/v1')
                    page.locator('#apiKey').fill('TEST_ONLY')
                    page.locator('#modelName').fill('test-model')
                    page.get_by_role('button', name='保存配置', exact=True).click()
                    group('growth')
                    expect(page.locator('#view-ai-report')).to_be_visible()
                    page.locator('#view-ai-report').get_by_role('button', name='生成新报告').click()
                    expect(page.locator('#aiReportList')).to_contain_text('新生成的复盘报告')
                    page.locator('#aiReportList .card').filter(has_text='新生成的复盘报告').get_by_role('button', name='删除').click()
                    page.locator('#modalBox').get_by_role('button', name='删除', exact=True).click()
                    expect(page.locator('#aiReportList')).not_to_contain_text('新生成的复盘报告')
                    expect(page.locator('#aiReportList')).to_contain_text('原有报告')
                    for destination in ('personal', 'actions', 'learning', 'records', 'growth'):
                        group(destination)
                        page.keyboard.press('Control+k')
                        expect(page.locator('#globalSearch')).to_be_focused()
                        page.locator('#globalSearch').fill('历史')
                        page.locator('#globalSearch').press('Enter')
                        expect(page.locator('#view-search')).to_be_visible()
                        expect(page.locator('#searchResults')).to_contain_text('保留的历史记录1')
                        expect(page.locator('[data-group][aria-current="page"]')).to_have_count(0)
                    page.locator('#searchTypeFilter').select_option('decision')
                    page.locator('#searchPagination').get_by_role('button', name='下一页').click()
                    expect(page.locator('#searchResults')).to_contain_text('保留的历史记录2')
                    page.locator('#searchResults .search-result-item').click()
                    expect(page.locator('#view-decisions')).to_be_visible()
                    shots = Path('/tmp/grow-round2-browser')
                    shots.mkdir(exist_ok=True)
                    for width in (320, 390, 768, 1280):
                        page.set_viewport_size({'width': width, 'height': 900})
                        for destination, tab in (('records', '时间线'), ('growth', '周期复盘')):
                            group(destination)
                            nav.get_by_role('button', name=tab, exact=True).click()
                            self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                        if width in (390, 1280):
                            expect(page.locator('#reportExport')).to_be_enabled()
                            page.screenshot(path=str(shots / f'cycle-review-{width}.png'), full_page=True)
                    page.reload()
                    group('growth')
                    nav.get_by_role('button', name='周期复盘').click()
                    expect(page.locator('#view-cycle-review')).to_be_visible()
                    self.assertTrue(any(path == '/api/timeline' and query.get('types') == ['decision'] for path, query in requests))
                    self.assertTrue(any(path == '/api/search' and query.get('page') == ['2'] for path, query in requests))
                    self.assertEqual(writes, [('POST', '/api/behavior-report/generate'), ('DELETE', '/api/behavior-report/2')])
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
