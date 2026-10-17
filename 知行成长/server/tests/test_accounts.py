"""Real PostgreSQL account and isolation acceptance tests (localhost only)."""
import os
import unittest
import importlib
import json
import tempfile
import uuid
import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import db
import httpx
import psycopg2
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from plans.github import GitHubContent
from test_github_plans import Repository, B, D


class PasswordTests(unittest.TestCase):
    def test_password_hash_is_salted_and_never_plaintext(self):
        from accounts import hash_password, verify_password
        first = hash_password('password-for-test')
        self.assertNotEqual(first, hash_password('password-for-test'))
        self.assertNotIn('password-for-test', first)
        self.assertTrue(verify_password('password-for-test', first))
        self.assertFalse(verify_password('wrong', first))
        self.assertFalse(verify_password('wrong', 'malformed'))


@unittest.skipUnless(os.getenv('TEST_ACCOUNTS_PG_DSN'), 'Requires dedicated localhost PostgreSQL')
class AccountIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['TEST_ACCOUNTS_PG_DSN']
        if 'host=127.0.0.1' not in self.dsn:
            raise RuntimeError('Only localhost is allowed')
        self.schema = 'accounts_test_' + uuid.uuid4().hex
        self.schemas = []
        with psycopg2.connect(self.dsn) as c:
            c.cursor().execute('CREATE SCHEMA ' + self.schema)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            'CLOUD_DEPLOY':'1', 'PLAN_CONTENT_BACKEND':'github',
            'RUNTIME_ROOT':self.tmp.name + '/runtime', 'LEARN_ROOT':self.tmp.name + '/materials',
            'APP_USERNAME':'owner', 'APP_PASSWORD':'OWNER-TEST-PASSWORD-24-CHARACTERS',
            'GITHUB_CONTENT_REPO':'owner/courses', 'GITHUB_CONTENT_BRANCH':'main',
            'GITHUB_CONTENT_TOKEN':'DEFAULT_TEST_SECRET',
            'ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode(),
        })
        self.env.start(); self.addCleanup(self.env.stop)
        database = patch.object(db, 'DATABASE_URL', self.dsn + ' options=-csearch_path=' + self.schema)
        database.start(); self.addCleanup(database.stop)
        self.repositories = {}
        original = GitHubContent.request
        def request(content, *args, **kwargs):
            def dispatch(req):
                parts = req.url.path.split('/')
                key = '/'.join(parts[2:4])
                repo = self.repositories.setdefault(key, Repository())
                url = req.url.copy_with(path='/repos/owner/courses/' + '/'.join(parts[4:]))
                return repo(httpx.Request(req.method, url, headers=req.headers, content=req.content))
            content.transport = httpx.MockTransport(dispatch)
            return original(content, *args, **kwargs)
        mock = patch.object(GitHubContent, 'request', request)
        mock.start(); self.addCleanup(mock.stop)
        import tenancy
        tenancy._proxies.clear()
        self.dashboard = importlib.reload(importlib.import_module('app'))
        self.dashboard.PENDING_SYNC_FILE = Path(self.tmp.name) / 'no-sync.json'
        self.client = TestClient(self.dashboard.app, base_url='https://learning.example')
        self.client.__enter__()
        self.addCleanup(self.cleanup_database)
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.headers = {'X-Copilot-Request':'1'}

    def cleanup_database(self):
        with psycopg2.connect(self.dsn) as c:
            cur = c.cursor()
            cur.execute('SELECT schema_name FROM ' + self.schema + '.auth_users WHERE is_owner=0')
            for row in cur.fetchall(): cur.execute('DROP SCHEMA ' + row[0] + ' CASCADE')
            cur.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def register(self, username='alice'):
        invitation = self.invite()
        response = self.client.post('/api/auth/register', json={'username':username, 'password':'user-password-123', 'invitation':invitation}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['user']

    def invite(self):
        if not self.dashboard.accounts.session(self.client.cookies.get('zhixing_session','')):
            response = self.login('owner',os.environ['APP_PASSWORD'])
            self.assertEqual(response.status_code,200,response.text)
        response = self.client.post('/api/account/invitations',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['path'].split('#invite=',1)[1]

    def login(self, username, password='user-password-123'):
        return self.client.post('/api/auth/login', json={'username':username,'password':password}, headers=self.headers)

    def test_registration_requires_an_invitation_and_anonymous_cannot_invite(self):
        response = self.client.post('/api/auth/register',json={'username':'outsider','password':'user-password-123'},headers=self.headers)
        self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(response.json()['error'],'invitation_required')
        self.assertEqual(self.client.post('/api/account/invitations',headers=self.headers).status_code,401)
        self.assertEqual(self.client.get('/api/account/invitations').status_code,401)
        with self.dashboard.accounts.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM auth_users WHERE is_owner=0').fetchone()[0],0)

    def test_invitation_is_single_use_expiring_and_revocable(self):
        invitation = self.invite()
        body = {'username':'alice','password':'user-password-123','invitation':invitation}
        self.assertEqual(self.client.post('/api/auth/register',json={**body,'invitation':'invalid'},headers=self.headers).status_code,403)
        self.assertEqual(self.client.post('/api/auth/register',json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/auth/register',json={**body,'username':'bob'},headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/api/account/invitations').json()['invitations'],[])
        created = self.client.post('/api/account/invitations',headers=self.headers).json()
        self.assertIn('path',created)
        token = created['path'].split('#invite=',1)[1]
        listing = self.client.get('/api/account/invitations').json()
        self.assertEqual(listing['invitations'][0]['status'],'active')
        self.assertNotIn(token,json.dumps(listing))
        with self.dashboard.accounts.conn() as c:
            saved = c.execute('SELECT token_hash FROM auth_invitations WHERE id=?',(created['id'],)).fetchone()[0]
            self.assertNotEqual(saved,token)
        self.assertEqual(self.client.delete('/api/account/invitations/' + created['id'],headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/auth/register',json={**body,'username':'bob','invitation':token},headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/api/account/invitations').json()['invitations'][0]['status'],'revoked')
        expired = self.invite()
        with self.dashboard.accounts.conn() as c:
            c.execute('UPDATE auth_invitations SET expires_at=0 WHERE inviter_id=(SELECT id FROM auth_users WHERE username=?)',('alice',))
        self.assertEqual(self.client.post('/api/auth/register',json={**body,'username':'bob','invitation':expired},headers=self.headers).status_code,403)
        self.login('owner',os.environ['APP_PASSWORD'])
        self.assertEqual(self.client.delete('/api/account/invitations/' + created['id'],headers=self.headers).status_code,404)
        listing = self.client.get('/api/account/invitations').json()['invitations']
        self.assertEqual(len(listing),1)
        self.assertEqual(listing[0]['status'],'used')
        self.assertEqual(self.client.delete('/api/account/invitations/' + listing[0]['id'],headers=self.headers).status_code,409)

    def test_concurrent_invitation_redemption_creates_only_one_account(self):
        from concurrent.futures import ThreadPoolExecutor
        invitation = self.invite()
        def redeem(username):
            client = TestClient(self.dashboard.app, base_url='https://learning.example')
            try:
                return client.post('/api/auth/register',json={'username':username,'password':'user-password-123','invitation':invitation},headers=self.headers).status_code
            finally: client.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(redeem,('alice','bob')))
        self.assertCountEqual(results,[200,403])
        with self.dashboard.accounts.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM auth_users WHERE is_owner=0').fetchone()[0],1)

    def test_duplicate_username_keeps_invitation_and_active_invites_are_limited(self):
        self.register('alice')
        invitation = self.invite()
        body = {'username':'alice','password':'user-password-123','invitation':invitation}
        self.assertEqual(self.client.post('/api/auth/register',json=body,headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/auth/register',json={**body,'username':'bob'},headers=self.headers).status_code,200)
        for _ in range(20):
            self.assertEqual(self.client.post('/api/account/invitations',headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/account/invitations',headers=self.headers).status_code,429)

    def post(self, path, data):
        response = self.client.post(path, json=data, headers=self.headers)
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()

    def test_registration_session_logout_validation_and_csrf(self):
        self.assertEqual(self.client.get('/api/data').status_code, 401)
        self.assertEqual(self.client.get('/', follow_redirects=False).headers['location'], '/login')
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        invitation = self.invite()
        for username in ('owner', '../public', 'a'):
            response = self.client.post('/api/auth/register', json={'username':username,'password':'short','invitation':invitation},headers=self.headers)
            self.assertIn(response.status_code, (409, 422))
        response = self.client.post('/api/auth/register', json={'username':'alice','password':'user-password-123','invitation':invitation}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie); self.assertIn('Secure', cookie); self.assertIn('SameSite=lax', cookie)
        with self.dashboard.accounts.conn() as c:
            user = dict(c.execute("SELECT * FROM auth_users WHERE username='alice'").fetchone())
            session = c.execute('SELECT digest FROM auth_sessions').fetchone()[0]
            self.assertNotEqual(session, self.client.cookies.get('zhixing_session'))
            self.assertNotIn('user-password', user['password_hash'])
        self.assertEqual(self.client.get('/api/auth/me').json()['user']['username'], 'alice')
        self.assertEqual(self.client.post('/api/auth/register',json={'username':'ALICE','password':'user-password-123','invitation':self.invite()},headers=self.headers).status_code,409)
        self.assertEqual(self.login('alice','wrong').status_code,401)
        self.assertEqual(self.client.post('/api/auth/logout', headers={**self.headers, 'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,403)
        token = self.client.cookies.get('zhixing_session')
        self.assertEqual(self.client.post('/api/auth/logout',headers=self.headers).status_code,200)
        self.client.cookies.set('zhixing_session', token)
        self.assertEqual(self.client.get('/api/data').status_code,401)
        self.client.cookies.clear()
        self.assertEqual(self.login('alice').status_code,200)
        with self.dashboard.accounts.conn() as c: c.execute('UPDATE auth_sessions SET expires_at=0')
        self.assertEqual(self.client.get('/api/data').status_code,401)

    def test_learning_records_and_objects_are_isolated_from_users_and_owner(self):
        self.login('owner', os.environ['APP_PASSWORD'])
        owner_state = self.client.get('/api/data').json()
        owner_state['todos'] = [{'id':'private','date':'2026-10-17','title':'OWNER PRIVATE'}]
        h = {**self.headers,'X-Legacy-State-Protocol':'1'}
        self.assertEqual(self.client.put('/api/data', json=owner_state, headers=h).status_code,200)
        alice = self.register()
        state = self.client.get('/api/data').json()
        self.assertEqual(state['todos'], [])
        state['reviews'] = [{'date':'2026-10-17','thought':'ALICE PRIVATE'}]
        self.assertEqual(self.client.put('/api/data',json=state,headers=h).status_code,200)
        ref = self.post('/api/reflections', {'record_date':'2026-10-17','raw_text':'ALICE REFLECTION','key':'alice-reflection'})
        stock = self.post('/api/stocks', {'stock_code':'123','stock_name':'ALICE STOCK','action':'buy','date':'2026-10-17','price':1})
        behavior = self.post('/api/behavior/applications', {'date':'2026-10-17','module_id':'renzhi','concept':'ALICE CONCEPT'})
        draft = self.post('/api/plans/drafts', {'data':{'brief':B,'document':D}})
        self.register('bob')
        self.assertEqual(self.client.get('/api/data').json()['reviews'], [])
        self.assertEqual(self.client.get('/api/reflections/' + ref['id']).status_code,404)
        self.assertEqual(self.client.get('/api/stocks/' + stock['id']).status_code,404)
        self.assertEqual(self.client.get('/api/behavior/applications/' + str(behavior['id'])).status_code,404)
        self.assertEqual(self.client.get('/api/plans/drafts/' + draft['id']).status_code,404)
        self.assertEqual(self.client.get('/api/study-materials').json()['modules'][0]['lessons'], [])
        stale_page = self.client.put('/api/data',json=state,headers={**h,'X-Account-Id':alice['id']})
        self.assertEqual(stale_page.status_code,409)
        self.assertEqual(stale_page.headers['X-Account-Changed'],'1')
        self.assertEqual(self.login('alice').status_code,200)
        self.assertEqual(self.client.get('/api/data').json()['reviews'][0]['thought'],'ALICE PRIVATE')
        self.assertEqual(self.client.get('/api/reflections/' + ref['id']).json()['entry']['raw_text'],'ALICE REFLECTION')
        self.assertEqual(self.login('owner',os.environ['APP_PASSWORD']).status_code,200)
        self.assertEqual(self.client.get('/api/data').json()['todos'][0]['title'],'OWNER PRIVATE')

    def test_default_and_custom_github_encryption_prefix_and_binding(self):
        alice = self.register()
        settings = self.client.get('/api/account/github').json()
        self.assertEqual(settings['repository'],'owner/courses')
        self.assertEqual(settings['prefix'],'用户/' + alice['id'] + '/')
        custom = {'mode':'custom','repository':'alice/courses','branch':'main','token':'ALICE_SECRET_TOKEN'}
        response = self.client.put('/api/account/github',json=custom,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('ALICE_SECRET_TOKEN',response.text)
        with self.dashboard.accounts.conn() as c:
            stored = c.execute('SELECT github_config FROM auth_users WHERE id=?',(alice['id'],)).fetchone()[0]
        self.assertNotIn('ALICE_SECRET_TOKEN',stored)
        draft = self.post('/api/plans/drafts',{'data':{'brief':B,'document':D}})
        adopted = self.post('/api/plans/drafts/' + draft['id'] + '/adopt',{'data':{'key':'adopt','expected_hash':draft['content_hash']}})
        files = self.repositories['alice/courses'].commits[self.repositories['alice/courses'].head]['files']
        self.assertTrue(any(p.startswith(settings['prefix'] + '学习计划/') for p in files))
        self.assertFalse(any(p.startswith('学习计划/') for p in files))
        self.assertIn('/%E7%94%A8%E6%88%B7/',adopted['github_url'])
        rotation = self.client.put('/api/account/github',json={**custom,'token':'ROTATED_TOKEN'},headers=self.headers)
        self.assertEqual(rotation.status_code,200,rotation.text)
        changed = self.client.put('/api/account/github',json={**custom,'repository':'alice/new'},headers=self.headers)
        self.assertEqual(changed.status_code,409,changed.text)
        self.register('bob')
        self.assertEqual(self.client.get('/api/account/github').json()['mode'],'default')
        self.assertEqual(self.client.get('/api/plans').json()['plans'],[])
        self.assertEqual(self.client.get('/api/plans/' + adopted['plan_id']).status_code,404)

    def test_login_rate_limit_is_persistent(self):
        for _ in range(20): self.assertEqual(self.login('missing','wrong').status_code,401)
        self.assertEqual(self.login('missing','wrong').status_code,429)

    def test_existing_legacy_cloud_content_keeps_repository_binding(self):
        user = self.register()
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        with self.dashboard.accounts.conn() as c:
            record = dict(c.execute('SELECT * FROM auth_users WHERE id=?',(user['id'],)).fetchone())
        from tenancy import current_user
        identity = current_user.set(record)
        try:
            with db.connect() as c:
                c.execute('INSERT INTO cloud_documents VALUES (?,?)',
                    ('每日认知与通识学习/每日课程/test.md',json.dumps({'storage':'github'})))
        finally: current_user.reset(identity)
        changed = self.client.put('/api/account/github',json={'mode':'custom','repository':'alice/another','branch':'main','token':'TEST_ONLY'},headers=self.headers)
        self.assertEqual(changed.status_code,409,changed.text)
        self.assertIn('迁移',changed.json()['message'])
        self.assertEqual(self.client.get('/api/account/github').json()['mode'],'default')

    def test_same_plan_ids_in_shared_default_repository_have_separate_paths(self):
        users = []
        plan_ids = []
        for username in ('alice','bob'):
            users.append(self.register(username))
            draft = self.post('/api/plans/drafts', {'data':{'brief':B,'document':D}})
            adopted = self.post('/api/plans/drafts/' + draft['id'] + '/adopt',
                                {'data':{'key':'same-operation','expected_hash':draft['content_hash']}})
            plan_ids.append(adopted['plan_id'])
            self.assertEqual(len(self.client.get('/api/plans').json()['plans']),1)
        self.assertEqual(plan_ids[0],plan_ids[1])
        repo = self.repositories['owner/courses']
        files = repo.commits[repo.head]['files']
        for user in users:
            prefix = '用户/' + user['id'] + '/学习计划/' + plan_ids[0] + '/'
            self.assertIn(prefix + '学习规划.md',files)
        self.assertFalse(any(path.startswith('学习计划/') for path in files))

    def test_missing_tenant_table_does_not_fall_back_to_owner_schema(self):
        user = self.register()
        self.assertEqual(self.client.get('/api/data').status_code,200)
        with self.dashboard.accounts.conn() as c:
            record = dict(c.execute('SELECT * FROM auth_users WHERE id=?',(user['id'],)).fetchone())
        from tenancy import current_user
        identity = current_user.set(record)
        try:
            # A connection must search only the tenant schema, even if the owner
            # has a table of the same name with sensitive rows.
            with db.connect() as c:
                c.execute('DROP TABLE todos')
            with self.assertRaises(psycopg2.errors.UndefinedTable):
                with db.connect() as c: c.execute('SELECT * FROM todos')
        finally:
            current_user.reset(identity)

    def test_lost_encryption_key_can_be_repaired_and_default_restored(self):
        user = self.register()
        custom = {'mode':'custom','repository':'alice/courses','branch':'main','token':'PRIVATE_TOKEN'}
        self.assertEqual(self.client.put('/api/account/github',json=custom,headers=self.headers).status_code,200)
        from tenancy import reset_user
        with patch.dict(os.environ, {'ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            reset_user(user['id'])
            self.assertEqual(self.client.get('/api/auth/me').status_code,200)
            self.assertEqual(self.client.get('/api/account/github').status_code,200)
            self.assertEqual(self.client.get('/api/plans').status_code,503)
            repaired = self.client.put('/api/account/github',json=custom,headers=self.headers)
            self.assertEqual(repaired.status_code,200,repaired.text)
            self.assertEqual(self.client.get('/api/plans').status_code,200)
            restored = self.client.put('/api/account/github',json={'mode':'default'},headers=self.headers)
            self.assertEqual(restored.status_code,200,restored.text)
            self.assertEqual(restored.json()['mode'],'default')
        self.assertEqual(self.client.get('/api/plans').status_code,200)

    def test_background_generation_keeps_identity_and_same_keys_are_independent(self):
        calls = []
        async def model(messages, cfg):
            calls.append(cfg['key'])
            await asyncio.sleep(1)
            yield {'text':json.dumps(D)}
            yield {'done':True}
        with patch('copilot.transport.qwen_stream', model):
            self.register('alice')
            for username in ('alice','bob'):
                if username == 'bob': self.register('bob')
                self.post('/api/plans/generate', {'data':{'kind':'plan','key':'same-key','brief':B,
                    'ai_config':{'api_base_url':'https://model.example/v1','api_key':username+'-SECRET','model_name':'test-model'}}})
                if username == 'alice':
                    busy = self.client.put('/api/account/github',json={'mode':'default'},headers=self.headers)
                    self.assertEqual(busy.status_code,409,busy.text)
                    self.assertIn('生成',busy.json()['message'])
            for username in ('alice','bob'):
                self.assertEqual(self.login(username).status_code,200)
                for _ in range(100):
                    attempt = self.client.get('/api/plans/attempts/same-key').json()
                    if attempt.get('state') not in ('queued','generating'): break
                    time.sleep(.02)
                self.assertEqual(attempt['state'],'ready',attempt)
                listing = self.client.get('/api/plans').json()
                self.assertEqual(len(listing['drafts']),1)
                self.assertNotIn('SECRET',json.dumps(listing))
            self.assertCountEqual(calls,['alice-SECRET','bob-SECRET'])


@unittest.skipUnless(os.getenv('RUN_ACCOUNTS_BROWSER') == '1', 'Opt-in Chromium acceptance test')
class AccountBrowserTests(AccountIntegrationTests):
    # Reuse the real app and DB fixture; this flow also checks account-specific
    # browser AI settings without reading credentials back into the test output.
    def test_browser_register_records_storage_logout_and_mobile(self):
        import socket
        import threading
        import uvicorn
        from playwright.sync_api import sync_playwright
        sock = socket.socket()
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(self.dashboard.app, host='127.0.0.1', port=port, lifespan='off', log_level='error')
        server = uvicorn.Server(config)
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        with patch.dict(os.environ, {'CLOUD_DEPLOY':'0'}):
            thread.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                    context = browser.new_context(viewport={'width':1360,'height':1000})
                    page = context.new_page()
                    errors = []
                    page.on('pageerror',lambda error: errors.append(str(error)))
                    url = f'http://127.0.0.1:{port}'
                    page.goto(url)
                    page.wait_for_url('**/login')
                    page.screenshot(path='/tmp/grow-accounts-login.png',full_page=True)
                    self.assertFalse(page.locator('#registerTab').is_visible())
                    page.get_by_label('用户名',exact=True).fill('owner')
                    page.get_by_label('密码',exact=True).fill(os.environ['APP_PASSWORD'])
                    page.get_by_role('button',name='登录',exact=True).last.click()
                    page.wait_for_url(url + '/')
                    page.get_by_role('button',name='设置',exact=True).click()
                    page.get_by_role('button',name='生成邀请链接',exact=True).click()
                    page.locator('#invitationResult:not([hidden])').wait_for()
                    alice_invite = page.locator('#invitationLink').input_value()
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.wait_for_url('**/login')
                    page.goto(alice_invite)
                    page.get_by_role('button',name='受邀注册',exact=True).wait_for()
                    page.get_by_label('用户名',exact=True).fill('browser_alice')
                    page.get_by_label('密码',exact=True).fill('browser-password-123')
                    page.get_by_label('确认密码',exact=True).fill('different-password')
                    page.get_by_role('button',name='注册并开始学习').click()
                    page.get_by_text('两次密码不一致，请重新填写。').wait_for()
                    page.get_by_label('确认密码',exact=True).fill('browser-password-123')
                    page.get_by_role('button',name='注册并开始学习').click()
                    page.wait_for_url(url + '/')
                    page.get_by_text('browser_alice',exact=True).wait_for()
                    page.locator('#todoInput0').fill('ALICE PRIVATE TODO')
                    page.locator('#todayTodos').get_by_role('button',name='添加',exact=True).click()
                    page.get_by_text('已保存 · 个人数据库',exact=True).wait_for()
                    page.get_by_role('button',name='设置',exact=True).click()
                    page.get_by_text('当前：owner/courses',exact=False).wait_for()
                    page.locator('#apiBaseUrl').fill('https://model.example/v1')
                    page.locator('#apiKey').fill('ALICE_BROWSER_SECRET')
                    page.locator('#modelName').fill('test-model')
                    page.get_by_role('button',name='保存配置',exact=True).click()
                    page.locator('#githubMode').select_option('custom')
                    page.get_by_label('仓库',exact=True).fill('alice/browser-courses')
                    page.get_by_label('GitHub Token',exact=True).fill('BROWSER_GITHUB_SECRET')
                    page.get_by_role('button',name='测试连接',exact=True).last.click()
                    page.get_by_text('仓库和分支可读取。',exact=False).wait_for()
                    page.get_by_role('button',name='保存存储配置',exact=True).click()
                    page.get_by_text('当前：alice/browser-courses',exact=False).wait_for()
                    page.get_by_role('button',name='生成邀请链接',exact=True).click()
                    page.locator('#invitationResult:not([hidden])').wait_for()
                    bob_invite = page.locator('#invitationLink').input_value()
                    page.screenshot(path='/tmp/grow-invitations-settings.png',full_page=True)
                    old_tab = context.new_page()
                    old_tab.goto(url)
                    old_tab.locator('#todoInput0').wait_for()
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.wait_for_url('**/login')
                    self.assertFalse(page.locator('#registerTab').is_visible())
                    page.goto(bob_invite)
                    page.get_by_label('用户名',exact=True).fill('browser_bob')
                    page.get_by_label('密码',exact=True).fill('browser-password-123')
                    page.get_by_label('确认密码',exact=True).fill('browser-password-123')
                    page.get_by_role('button',name='注册并开始学习').click()
                    page.wait_for_url(url + '/')
                    page.get_by_text('browser_bob',exact=True).wait_for()
                    self.assertEqual(page.get_by_text('ALICE PRIVATE TODO',exact=True).count(),0)
                    old_tab.locator('#todoInput0').fill('STALE ALICE TODO')
                    old_tab.locator('#todayTodos').get_by_role('button',name='添加',exact=True).click()
                    old_tab.get_by_text('当前账号已变更',exact=True).wait_for()
                    page.get_by_role('button',name='设置',exact=True).click()
                    self.assertEqual(page.locator('#apiKey').input_value(),'')
                    page.get_by_text('当前：owner/courses',exact=False).wait_for()
                    page.get_by_role('button',name='退出登录',exact=True).click()
                    page.wait_for_url('**/login')
                    page.get_by_label('用户名',exact=True).fill('browser_alice')
                    page.get_by_label('密码',exact=True).fill('browser-password-123')
                    page.get_by_role('button',name='登录',exact=True).last.click()
                    page.wait_for_url(url + '/')
                    page.get_by_text('ALICE PRIVATE TODO',exact=True).wait_for()
                    self.assertEqual(page.get_by_text('STALE ALICE TODO',exact=True).count(),0)
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='设置',exact=True).click()
                    page.get_by_text('当前：alice/browser-courses',exact=False).wait_for()
                    page.get_by_role('button',name='生成邀请链接',exact=True).click()
                    page.locator('#invitationResult:not([hidden])').wait_for()
                    page.get_by_role('button',name='撤销邀请',exact=True).click()
                    page.get_by_text('邀请已撤销。',exact=True).wait_for()
                    self.assertTrue(page.locator('#invitationResult').is_hidden())
                    page.screenshot(path='/tmp/grow-invitations-mobile.png',full_page=True)
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=10)


if __name__ == '__main__':
    unittest.main()
