"""Navigation audit regressions against synthetic records and intercepted APIs only."""
import functools
import json
import os
import threading
import unittest
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome')
class NavigationAuditBrowser(unittest.TestCase):
    def test_shared_filters_compact_panels_and_topic_records(self):
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
        modules = [{'id': 'renzhi', 'name': '认知与通识学习完整分类名称', 'color': '#4F6EF7'}]
        legacy = dict(modules=modules, checkins={day: {'renzhi': 1}}, habits={},
                      customFields=[{'key': 'topic', 'label': '专题内容', 'type': 'text'}],
                      customRecords=[{'topic': '已有记录继续保留'}], decisions=[], predictions=[],
                      reviews=[], insights=[], todos=[], _revision='fixture')
        nodes = [{'id': 1, 'name': '证据推理', 'category': '概念', 'summary': '判断证据', 'source': '来源一'},
                 {'id': 2, 'name': '证据清单', 'category': '工具', 'summary': '检查证据', 'source': '来源二'},
                 {'id': 3, 'name': '概率更新', 'category': '概念', 'summary': '贝叶斯', 'source': '来源三'},
                 {'id': 4, 'name': '未分类节点', 'category': None, 'summary': '备用材料', 'source': '来源四'}]
        links = [{'source_id': 1, 'target_id': 3, 'weight': 1}]
        plan = dict(id='p1', title='保留正在执行的学习行动', period='day', status='active',
                    start_date=day, end_date=day, at='09:00', timezone='Asia/Shanghai', target_minutes=20,
                    minimum_minutes=5, completion_mode='time', target={'kind': 'book'}, revision=1,
                    progress=dict(completed=0, minimum=0, minutes=0), blocked=False)
        execution = dict(id='e1', plan_id='p1', title=plan['title'], planned_minutes=20,
                         started_at=stamp, target=plan['target'], outcome='running')
        writes, errors = [], []
        fail_graph = False

        def fixture(route):
            nonlocal execution
            req = route.request
            parsed = urlsplit(req.url)
            path = parsed.path
            if req.method != 'GET':
                writes.append((req.method, path))
            empty = dict(invitations=[], modules=[], lessons=[], plans=[], records=[], items=[], articles=[],
                         jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[],
                         legacy=[], drafts=[])
            result = empty
            if path == '/api/auth/me':
                result = {'user': {'id': 'audit-fixture', 'username': 'tester', 'is_owner': False}}
            elif path == '/api/data':
                if req.method == 'PUT':
                    legacy.update(req.post_data_json)
                    result = {'state': legacy, 'assigned_ids': {}}
                else:
                    result = legacy
            elif path == '/api/action-plans':
                result = dict(plans=[plan], execution=execution, server_time=stamp, action_schema_version=2)
            elif path == '/api/action-plans/p1/operations':
                values = req.post_data_json
                self.assertEqual(values['action'], 'finish')
                self.assertEqual(values['actual_minutes'], 10)
                execution = None
                result = dict(plan=plan, execution={'id': 'e1', 'outcome': 'completed'})
            elif path == '/api/knowledge':
                result = dict(nodes=nodes, total=len(nodes), categories={'概念': 2, '工具': 1})
            elif path == '/api/knowledge/graph':
                if fail_graph:
                    route.fulfill(status=503, body='{}', content_type='application/json')
                    return
                category = parse_qs(parsed.query).get('category', [''])[0]
                selected = [n for n in nodes if not category or n['category'] == category]
                result = dict(nodes=selected, links=links, stats=dict(total_nodes=3, total_links=1, categories={}))
            elif path == '/api/knowledge/scan':
                result = {'count': 3}
            elif path == '/api/knowledge/scan-links':
                result = {'links_created': 1}
            elif path == '/api/reading/library':
                result = {'jobs': [dict(id='j1', kind='summary', state='ready', article_id='a1', title='已完成的阅读总结')]}
            elif path == '/api/reading/jobs/j1':
                result = dict(id='j1', kind='summary', state='ready', article_id='a1', title='已完成的阅读总结')
            elif path == '/api/behavior-report':
                result = []
            route.fulfill(body=json.dumps(result), content_type='application/json')

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv(
                    'CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960}, timezone_id='Asia/Shanghai')
                    page.route('**/api/**', fixture)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base)
                    group = lambda key: page.locator(f'[data-group="{key}"]').click()
                    sub = page.locator('#subnav')
                    group('records')
                    sub.get_by_role('button', name='专题记录', exact=True).click()
                    expect(page.locator('#recordTable')).to_contain_text('已有记录继续保留')
                    expect(page.locator('#customFieldSettings')).not_to_have_attribute('open', '')
                    page.locator('#view-custom').get_by_role('button', name='新增记录', exact=True).click()
                    expect(page.locator('#rf_topic')).to_be_visible()
                    page.get_by_role('button', name='取消', exact=True).click()
                    group('learning')
                    sub.get_by_role('button', name='课程规划', exact=True).click()
                    expect(page.locator('#view-plans h2')).to_have_text('课程规划')
                    expect(page.get_by_role('button', name='创建课程规划', exact=True)).to_be_visible()
                    group('growth')
                    sub.get_by_role('button', name='知识图谱', exact=True).click()
                    expect(page.locator('#graphContainer circle')).to_have_count(4)
                    page.locator('#knowledgeSearch').fill('证据')
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    expect(page.locator('#knowledgeList b')).to_have_count(2)
                    page.locator('#graphCategoryFilter').select_option('概念')
                    expect(page.locator('#graphContainer circle')).to_have_count(1)
                    expect(page.locator('#knowledgeList b')).to_have_count(1)
                    page.locator('#knowledgeSearch').fill('没有此节点')
                    expect(page.locator('#graphContainer')).to_contain_text('暂无匹配节点')
                    expect(page.locator('#knowledgeList')).to_contain_text('暂无匹配节点')
                    page.wait_for_timeout(100)
                    expect(page.locator('#graphContainer')).to_contain_text('暂无匹配节点')
                    page.locator('#knowledgeSearch').fill('贝叶斯')
                    expect(page.locator('#graphContainer circle')).to_have_count(1)
                    expect(page.locator('#knowledgeList b')).to_have_text('概率更新')
                    page.locator('#knowledgeSearch').fill('')
                    page.locator('#graphCategoryFilter').select_option('未分类')
                    expect(page.locator('#graphContainer circle')).to_have_count(1)
                    expect(page.locator('#knowledgeList b')).to_have_text('未分类节点')
                    page.locator('#graphCategoryFilter').select_option('概念')
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    # Late responses from a previous category must not replace the current graph.
                    held = []
                    page.route('**/api/knowledge/graph?limit=1000&category=*',
                               lambda route: held.append(route) if '%E5%B7%A5%E5%85%B7' in route.request.url else fixture(route))
                    page.locator('#graphCategoryFilter').select_option('工具')
                    page.wait_for_timeout(100)
                    self.assertEqual(len(held), 1)
                    page.locator('#graphCategoryFilter').select_option('概念')
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    held.pop().fulfill(body=json.dumps(dict(nodes=[nodes[1]], links=[], stats={})),
                                       content_type='application/json')
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    expect(page.locator('#knowledgeList b')).to_have_count(2)
                    page.unroute('**/api/knowledge/graph?limit=1000&category=*')
                    page.locator('#graphCategoryFilter').select_option('工具')
                    expect(page.locator('#graphContainer circle')).to_have_count(1)
                    fail_graph = True
                    page.locator('#graphCategoryFilter').select_option('概念')
                    expect(page.get_by_role('button', name='重试图谱', exact=True)).to_be_visible()
                    expect(page.locator('#knowledgeList b')).to_have_count(2)
                    expect(page.locator('#knowledgeFilterStatus')).to_contain_text('图谱暂时不可用')
                    fail_graph = False
                    page.get_by_role('button', name='重试图谱', exact=True).click()
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    page.get_by_role('button', name='扫描内容', exact=True).click()
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    expect(page.locator('#graphCategoryFilter')).to_have_value('概念')
                    page.get_by_role('button', name='扫描关系', exact=True).click()
                    expect(page.locator('#graphContainer circle')).to_have_count(2)
                    expect(page.locator('#knowledgeStats')).not_to_contain_text('工具')
                    # Both panels begin compact, share one dock, and leave room at page end.
                    expect(page.locator('#readingTaskCenter')).to_be_visible()
                    expect(page.locator('#actionExecution')).to_be_visible()
                    for panel in ('readingTaskCenter', 'actionExecution'):
                        expect(page.locator(f'#{panel} details')).not_to_have_attribute('open', '')
                    shots = Path(os.getenv('NAV_SCREENSHOT_DIR', '/tmp/grow-navigation-audit-after'))
                    shots.mkdir(parents=True, exist_ok=True)
                    for width in (320, 768, 1024, 1440):
                        page.set_viewport_size({'width': width, 'height': 960})
                        for expanded in (True, False):
                            for panel in ('readingTaskCenter', 'actionExecution'):
                                page.locator(f'#{panel} summary').click()
                            expect(page.locator('#actionExecution details')).to_have_js_property('open', expanded)
                            page.locator('#knowledgeList').scroll_into_view_if_needed()
                            page.keyboard.press('ControlOrMeta+End')
                            page.wait_for_timeout(100)
                            bounds = page.evaluate('''() => {
                              const a=document.getElementById('readingTaskCenter').getBoundingClientRect();
                              const b=document.getElementById('actionExecution').getBoundingClientRect();
                              const dock=document.getElementById('floatingPanels').getBoundingClientRect();
                              const last=document.getElementById('knowledgeList').getBoundingClientRect();
                              return {overlap:a.bottom>b.top, covered:last.bottom>dock.top,
                                overflow:document.documentElement.scrollWidth>innerWidth,
                                reserved:parseFloat(getComputedStyle(document.body).paddingBottom),height:dock.height};
                            }''')
                            self.assertFalse(bounds['overlap'], bounds)
                            self.assertFalse(bounds['covered'], bounds)
                            self.assertFalse(bounds['overflow'], bounds)
                            self.assertAlmostEqual(bounds['reserved'], bounds['height'], delta=1)
                        page.screenshot(path=str(shots / f'knowledge-{width}.png'), full_page=True)
                        page.screenshot(path=str(shots / f'panels-{width}.png'))
                    # Timer controls still open the original execution confirmation.
                    page.locator('#actionExecution summary').focus()
                    page.keyboard.press('Space')
                    page.locator('#actionExecution').get_by_role('button', name='记录完成', exact=True).click()
                    page.get_by_role('spinbutton', name='实际执行分钟', exact=True).fill('10')
                    page.get_by_role('button', name='确认并记录', exact=True).click()
                    expect(page.locator('#actionExecution')).to_be_hidden()
                    expect(page.locator('#readingTaskCenter')).to_be_visible()
                    page.locator('#readingTaskCenter summary').click()
                    page.locator('#readingTaskCenter').get_by_role('button', name='移除记录', exact=True).click()
                    expect(page.locator('#readingTaskCenter')).to_be_hidden()
                    expect(page.locator('#floatingPanels')).to_have_css('height', '0px')
                    group('growth')
                    sub.get_by_role('button', name='成长总览', exact=True).click()
                    page.locator('#view-overview summary', has_text='学习变化与活动明细').click()
                    expect(page.locator('#barChart')).to_contain_text(modules[0]['name'])
                    page.set_viewport_size({'width': 320, 'height': 960})
                    page.locator('#barChart').scroll_into_view_if_needed()
                    page.screenshot(path=str(shots / 'chart-320.png'))
                    legacy['customFields'] = []
                    page.reload()
                    group('records')
                    sub.get_by_role('button', name='专题记录', exact=True).click()
                    page.locator('#view-custom').get_by_role('button', name='新增记录', exact=True).click()
                    expect(page.locator('#customFieldSettings')).to_have_attribute('open', '')
                    expect(page.locator('#newFieldLabel')).to_be_focused()
                    self.assertEqual(errors, [])
                    self.assertEqual(writes, [('POST', '/api/knowledge/scan'), ('POST', '/api/knowledge/scan-links'),
                                              ('POST', '/api/action-plans/p1/operations')])
                    self.assertEqual(legacy['customRecords'], [{'topic': '已有记录继续保留'}])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
