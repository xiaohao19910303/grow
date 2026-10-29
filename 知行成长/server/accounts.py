"""Database-backed accounts, revocable sessions and encrypted GitHub preferences."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from contextlib import contextmanager

import db
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg2 import sql
from starlette.concurrency import run_in_threadpool

from copilot.core import Problem, fail
from tenancy import current_user, reset_user

COOKIE = 'zhixing_session'
SESSION_SECONDS = 7 * 86400
INVITATION_SECONDS = 7 * 86400
USERNAME = re.compile(r'^[a-zA-Z0-9_\-]{3,32}$')


def hash_password(password):
    salt = secrets.token_bytes(16)
    value = Scrypt(salt=salt, length=64, n=32768, r=8, p=3).derive(password.encode())
    return 'scrypt$' + salt.hex() + '$' + value.hex()


def verify_password(password, stored):
    try:
        kind, salt, expected = stored.split('$')
        if kind != 'scrypt': return False
        actual = Scrypt(salt=bytes.fromhex(salt), length=64, n=32768, r=8, p=3).derive(password.encode())
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256, repr=False)


class Registration(Credentials):
    invitation: str = Field(default='', max_length=128, repr=False)


class GitHubSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: str = 'default'
    repository: str = Field(default='', max_length=160)
    branch: str = Field(default='main', max_length=160)
    token: str = Field(default='', max_length=1000, repr=False)


def cipher():
    key = os.getenv('ACCOUNT_ENCRYPTION_KEY', '')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        fail('encryption_config', '服务端需要配置 ACCOUNT_ENCRYPTION_KEY 后才能保存个人 GitHub 凭证。', 503)


def content_for(user=None, settings=None):
    from plans.github import GitHubContent
    user = user or current_user.get()
    settings = settings if settings is not None else (json.loads(user['github_config']) if user else {})
    if settings.get('mode') == 'custom':
        try:
            token = cipher().decrypt(settings['token'].encode()).decode()
        except (InvalidToken, KeyError):
            fail('encryption_config', 'GitHub 凭证无法解密，请重新保存配置或恢复原加密密钥。', 503)
        content = GitHubContent(settings['repository'], settings['branch'], token)
    else:
        content = GitHubContent.from_env()
    content.prefix = '' if not user or user['is_owner'] else '用户/' + user['id'] + '/'
    return content


def public_user(user):
    return {key: user[key] for key in ('id', 'username', 'is_owner')}


class Accounts:
    def __init__(self):
        self.schema = None
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    @contextmanager
    def conn(self):
        with db.connect(tenant=False) as c:
            if self.schema:
                c._conn.cursor().execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
            yield c

    def initialize(self):
        with self.conn() as c:
            self.schema = c.execute('SELECT current_schema()').fetchone()[0]
            c.executescript('''
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                schema_name TEXT UNIQUE NOT NULL, is_owner INTEGER NOT NULL DEFAULT 0,
                github_config TEXT NOT NULL DEFAULT '{}', created_at BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_sessions (
                digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES auth_users(id), expires_at BIGINT NOT NULL);
            CREATE INDEX IF NOT EXISTS auth_session_expiry ON auth_sessions(expires_at);
            CREATE TABLE IF NOT EXISTS auth_limits (
                bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_invitations (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                inviter_id TEXT NOT NULL REFERENCES auth_users(id),
                created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
                used_by TEXT REFERENCES auth_users(id), revoked INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS auth_invitation_inviter ON auth_invitations(inviter_id);
            ''')
            password = os.getenv('APP_PASSWORD', '')
            if len(password) >= 24:
                c.execute('''INSERT INTO auth_users (id,username,password_hash,schema_name,is_owner,created_at)
                    VALUES (?,?,?,?,1,?) ON CONFLICT(id) DO NOTHING''',
                    ('owner', os.getenv('APP_USERNAME', 'owner').lower(), hash_password(password), self.schema, int(time.time())))
                owner = c.execute("SELECT password_hash FROM auth_users WHERE id='owner'").fetchone()
                if owner and not verify_password(password, owner[0]):
                    c.execute("UPDATE auth_users SET password_hash=? WHERE id='owner'", (hash_password(password),))
                    c.execute("DELETE FROM auth_sessions WHERE user_id='owner'")

    def throttle(self, peer):
        now = int(time.time())
        bucket = hashlib.sha256(peer.encode()).hexdigest()
        with self.conn() as c:
            c.execute('DELETE FROM auth_limits WHERE expires_at<?', (now,))
            row = c.execute('''INSERT INTO auth_limits VALUES (?,1,?)
                ON CONFLICT(bucket) DO UPDATE SET attempts=auth_limits.attempts+1
                RETURNING attempts''', (bucket, now + 900)).fetchone()
        if row[0] > 20: fail('rate_limited', '尝试次数过多，请 15 分钟后再试。', 429)

    def register(self, credentials):
        if not credentials.invitation:
            fail('invitation_required', '本平台仅限邀请注册，请向已有账号的用户获取邀请链接。', 403)
        username = credentials.username.strip().lower()
        if not USERNAME.fullmatch(username):
            fail('invalid', '用户名需为 3–32 位字母、数字、下划线或短横线。', 422)
        if len(credentials.password) < 10:
            fail('invalid', '密码至少需要 10 个字符。', 422)
        if username == os.getenv('APP_USERNAME', 'owner').lower():
            fail('username_taken', '此用户名不可用，请换一个。', 409)
        uid = uuid.uuid4().hex
        try:
            with self.conn() as c:
                invitation = c.execute('SELECT * FROM auth_invitations WHERE token_hash=? FOR UPDATE',
                    (hashlib.sha256(credentials.invitation.encode()).hexdigest(),)).fetchone()
                if not invitation or invitation['revoked'] or invitation['used_by'] or invitation['expires_at'] <= int(time.time()):
                    fail('invalid_invitation', '邀请已失效、已使用或已撤销，请获取新的邀请链接。', 403)
                c.execute('''INSERT INTO auth_users (id,username,password_hash,schema_name,created_at)
                    VALUES (?,?,?,?,?)''', (uid, username, hash_password(credentials.password), 'learner_' + uid, int(time.time())))
                c._conn.cursor().execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier('learner_' + uid)))
                # Creating the account, schema and consuming the invitation are atomic.
                c.execute('UPDATE auth_invitations SET used_by=? WHERE id=?', (uid, invitation['id']))
                return dict(c.execute('SELECT * FROM auth_users WHERE id=?', (uid,)).fetchone())
        except db.psycopg2.errors.UniqueViolation:
            fail('username_taken', '此用户名不可用，请换一个。', 409)

    def invitations(self, user):
        now = int(time.time())
        with self.conn() as c:
            rows = c.execute('''SELECT id,created_at,expires_at,used_by,revoked FROM auth_invitations
                WHERE inviter_id=? ORDER BY created_at DESC,id DESC LIMIT 100''', (user['id'],)).fetchall()
        return {'invitations': [{'id':row['id'], 'created_at':row['created_at'], 'expires_at':row['expires_at'],
            'status': 'used' if row['used_by'] else 'revoked' if row['revoked'] else 'expired' if row['expires_at'] <= now else 'active'} for row in rows]}

    def create_invitation(self, user):
        token = secrets.token_urlsafe(32)
        identity = uuid.uuid4().hex
        now = int(time.time())
        with self.conn() as c:
            # Serialize per-inviter creation so the active-link limit cannot race.
            c.execute('SELECT id FROM auth_users WHERE id=? FOR UPDATE', (user['id'],)).fetchone()
            active = c.execute('''SELECT COUNT(*) FROM auth_invitations WHERE inviter_id=?
                AND used_by IS NULL AND revoked=0 AND expires_at>?''', (user['id'],now)).fetchone()[0]
            if active >= 20: fail('invitation_limit', '最多保留 20 个有效邀请，请先使用或撤销已有邀请。', 429)
            c.execute('''INSERT INTO auth_invitations (id,token_hash,inviter_id,created_at,expires_at)
                VALUES (?,?,?,?,?)''', (identity,hashlib.sha256(token.encode()).hexdigest(),user['id'],now,now + INVITATION_SECONDS))
        # Fragment keeps the invitation secret out of server URL/access logs.
        return {'id':identity, 'path':'/login#invite=' + token, 'expires_at':now + INVITATION_SECONDS}

    def revoke_invitation(self, user, invitation_id):
        with self.conn() as c:
            row = c.execute('SELECT used_by FROM auth_invitations WHERE id=? AND inviter_id=? FOR UPDATE',
                            (invitation_id,user['id'])).fetchone()
            if not row: fail('not_found', '邀请不存在。', 404)
            if row['used_by']: fail('invitation_used', '邀请已使用，不能撤销已注册的账号。')
            c.execute('UPDATE auth_invitations SET revoked=1 WHERE id=?', (invitation_id,))
        return {'ok':True}

    def login(self, credentials):
        with self.conn() as c:
            row = c.execute('SELECT * FROM auth_users WHERE username=?', (credentials.username.strip().lower(),)).fetchone()
        valid = verify_password(credentials.password, row['password_hash'] if row else self.dummy_hash)
        if not row or not valid: fail('invalid_credentials', '用户名或密码不正确。', 401)
        return dict(row)

    def session(self, token):
        if not token or len(token) > 128: return None
        with self.conn() as c:
            row = c.execute('''SELECT u.* FROM auth_users u JOIN auth_sessions s ON s.user_id=u.id
                WHERE s.digest=? AND s.expires_at>?''',
                (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        return dict(row) if row else None

    def owner(self):
        with self.conn() as c:
            row = c.execute("SELECT * FROM auth_users WHERE id='owner' AND is_owner=1").fetchone()
        return dict(row) if row else None

    def revoke(self, token):
        with self.conn() as c:
            c.execute('DELETE FROM auth_sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def signed_in(self, user, request):
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.conn() as c:
            c.execute('DELETE FROM auth_sessions WHERE expires_at<?', (now,))
            c.execute('INSERT INTO auth_sessions VALUES (?,?,?)',
                      (hashlib.sha256(token.encode()).hexdigest(), user['id'], now + SESSION_SECONDS))
        response = JSONResponse({'user': public_user(user)})
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.url.scheme == 'https' or os.getenv('CLOUD_DEPLOY') == '1', samesite='lax')
        return response

    def settings(self, user):
        stored = json.loads(user['github_config'])
        custom = stored.get('mode') == 'custom'
        return {'mode': 'custom' if custom else 'default',
                'repository': stored.get('repository', '') if custom else os.getenv('GITHUB_CONTENT_REPO', ''),
                'branch': stored.get('branch', 'main') if custom else os.getenv('GITHUB_CONTENT_BRANCH', 'main'),
                'token_configured': bool(stored.get('token')) if custom else bool(os.getenv('GITHUB_CONTENT_TOKEN')),
                'prefix': '' if user['is_owner'] else '用户/' + user['id'] + '/',
                'encryption_ready': bool(os.getenv('ACCOUNT_ENCRYPTION_KEY'))}

    def candidate(self, user, body):
        if body.mode == 'default': return {}
        if body.mode != 'custom': fail('invalid', '存储模式只能为 default 或 custom。', 422)
        stored = json.loads(user['github_config'])
        token = cipher().encrypt(body.token.strip().encode()).decode() if body.token.strip() else stored.get('token', '')
        if not token: fail('invalid', '首次配置需要填写 GitHub Token。', 422)
        result = {'mode': 'custom', 'repository': body.repository.strip(), 'branch': body.branch.strip(), 'token': token}
        content_for(user, result).validate()
        return result

    def save_settings(self, user, body):
        candidate = self.candidate(user, body)
        content = content_for(user, candidate)
        content.validate()
        # This is a read-only access/branch check; it never initializes a repository.
        content.head()
        from copilot.core import digest
        with db.connect() as c:
            # Share publication and generation locks with all writers, including async tasks.
            for name in ('learning-plan-generation', 'learning-plan-publications'):
                lock_id = int(digest(user['schema_name'] + ':' + name)[:15], 16)
                if not c.execute('SELECT pg_try_advisory_xact_lock(?)', (lock_id,)).fetchone()[0]:
                    fail('busy', '生成或发布进行中，请完成后再修改存储配置。')
            # 快照任务运行期间保持账号服务实例稳定，避免存储配置重置使后台恢复误判中断。
            for table, column in (('learning_ai_attempts', 'state'), ('reflection_ai_attempts', 'status'), ('study_generation_jobs', 'state'),
                                  ('behavior_report_jobs','state'),('copilot_background_jobs','state'),
                                  ('course_continuation_jobs','state'),('investment_analysis_jobs','state')):
                if c.execute('SELECT to_regclass(?)', (table,)).fetchone()[0]:
                    active = c.execute(f"SELECT COUNT(*) FROM {table} WHERE data::jsonb->>'{column}' IN ('queued','generating','running')").fetchone()[0]
                    if active: fail('busy', '生成进行中，请完成或取消后再修改存储配置。')
            if c.execute("SELECT to_regclass('copilot_generation_attempts')").fetchone()[0]:
                if c.execute("SELECT COUNT(*) FROM copilot_generation_attempts WHERE status='generating'").fetchone()[0]:
                    fail('busy', '生成进行中，请完成或取消后再修改存储配置。')
            if c.execute("SELECT to_regclass('reading_records')").fetchone()[0]:
                if c.execute("SELECT COUNT(*) FROM reading_records WHERE data::jsonb->>'type'='job' AND data::jsonb->>'state' IN ('queued','running')").fetchone()[0]:
                    fail('busy', '阅读任务进行中，请完成或取消后再修改存储配置。')
            if c.execute("SELECT to_regclass('cloud_content_settings')").fetchone()[0]:
                bound = c.execute("SELECT data FROM cloud_content_settings WHERE id='binding'").fetchone()
                target = {'repository':content.repository,'branch':content.branch,'prefix':content.prefix}
                if bound and json.loads(bound[0]) != target:
                    published = c.execute("SELECT COUNT(*) FROM cloud_documents WHERE data::jsonb->>'storage'='github'").fetchone()[0]
                    pending = c.execute("SELECT COUNT(*) FROM cloud_publications WHERE data::jsonb->>'state'!='done'").fetchone()[0]
                    if published or pending:
                        fail('migration_required', '已有正式课程、阅读资料或待恢复发布，不能直接更换仓库或分支。请先迁移内容；仍可更新当前仓库的 Token。')
            installed = c.execute("SELECT to_regclass('learning_settings')").fetchone()[0]
            if installed:
                bound = c.execute("SELECT data FROM learning_settings WHERE id='content-storage'").fetchone()
                target = {'repository': content.repository, 'branch': content.branch}
                if content.prefix: target['prefix'] = content.prefix
                if bound and json.loads(bound[0])['binding'] != target:
                    count = c.execute('SELECT COUNT(*) FROM learning_plans').fetchone()[0]
                    pending = c.execute("SELECT COUNT(*) FROM learning_publications WHERE data::jsonb->>'state'='pending'").fetchone()[0]
                    if count or pending:
                        fail('migration_required', '已有正式计划或待恢复发布，不能直接更换仓库或分支。请先迁移内容；仍可更新当前仓库的 Token。')
                    c.execute("DELETE FROM learning_settings WHERE id='content-storage'")
            # Configuration and binding changes commit together on the tenant connection.
            c._conn.cursor().execute(sql.SQL('UPDATE {}.auth_users SET github_config=%s WHERE id=%s').format(
                sql.Identifier(self.schema)), (json.dumps(candidate), user['id']))
        reset_user(user['id'])
        return self.settings({**user, 'github_config': json.dumps(candidate)})


def install(app, static_dir, prepare_user):
    accounts = Accounts()
    app.state.accounts = accounts
    router = APIRouter(prefix='/api/auth')

    @router.post('/register')
    def register(body: Registration, request: Request):
        accounts.throttle(request.client.host if request.client else '')
        user = accounts.register(body)
        return accounts.signed_in(user, request)

    @router.post('/login')
    def login(body: Credentials, request: Request):
        accounts.throttle(request.client.host if request.client else '')
        user = accounts.login(body)
        accounts.revoke(request.cookies.get(COOKIE, ''))
        return accounts.signed_in(user, request)

    @router.post('/logout')
    def logout(request: Request):
        accounts.revoke(request.cookies.get(COOKIE, ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @router.get('/me')
    def me(): return {'user': public_user(current_user.get())}

    @app.get('/api/account/invitations')
    def invitations(): return accounts.invitations(current_user.get())

    @app.post('/api/account/invitations')
    def create_invitation(): return accounts.create_invitation(current_user.get())

    @app.delete('/api/account/invitations/{invitation_id}')
    def revoke_invitation(invitation_id: str): return accounts.revoke_invitation(current_user.get(), invitation_id)

    @app.get('/api/account/github')
    def github_settings(): return accounts.settings(current_user.get())

    @app.put('/api/account/github')
    def save_github(body: GitHubSettings): return accounts.save_settings(current_user.get(), body)

    @app.post('/api/account/github/test')
    def test_github(body: GitHubSettings):
        content = content_for(current_user.get(), accounts.candidate(current_user.get(), body))
        content.validate()
        content.head()
        return {'ok': True, 'message': '仓库和分支可读取。正式发布还需要 Contents 写权限。'}

    @app.get('/login', include_in_schema=False)
    def login_page(): return FileResponse(static_dir / 'login.html')

    app.include_router(router)

    @app.middleware('http')
    async def authenticate(request, call_next):
        path = request.url.path
        public = path in ('/login', '/api/health', '/api/auth/register', '/api/auth/login') or path.startswith('/static/')
        if path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if (origin and origin != f'{request.url.scheme}://{request.url.netloc}') or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'message': '拒绝跨来源请求。'}, status_code=403)
            if request.headers.get('x-copilot-request') != '1':
                return JSONResponse({'message': '写操作需要同源请求标识。'}, status_code=403)
            length = request.headers.get('content-length', '0')
            if not length.isdecimal():
                return JSONResponse({'message': '请求长度无效。'}, status_code=400)
            if int(length) > 500000:
                return JSONResponse({'message': '请求内容过长。'}, status_code=413)
        token = None
        try:
            if not public:
                user = await run_in_threadpool(accounts.session, request.cookies.get(COOKIE, ''))
                # Existing daily-reading automation uses GitHub OIDC, scoped to
                # this one route. It cannot log in, invite users or read other APIs.
                if not user and path == '/api/reading/scheduled-run' and request.method in ('GET','POST'):
                    from reading.scheduled import authorized
                    if await run_in_threadpool(authorized, request):
                        user = await run_in_threadpool(accounts.owner)
                if not user:
                    return JSONResponse({'message': '请先登录。', 'code': 'login_required'}, status_code=401,
                                        headers={'Cache-Control':'no-store'}) if path.startswith('/api/') else RedirectResponse('/login', status_code=303, headers={'Cache-Control':'no-store'})
                page_user = request.headers.get('x-account-id')
                if path.startswith('/api/') and page_user and page_user != user['id']:
                    return JSONResponse({'message': '账号已变更，请重新打开页面。'}, status_code=409,
                                        headers={'X-Account-Changed': '1', 'Cache-Control': 'no-store'})
                token = current_user.set(user)
                request.state.user = user
                await run_in_threadpool(prepare_user, user)
            response = await call_next(request)
        except Problem as exc:
            response = JSONResponse({'code': exc.code, 'message': exc.message}, status_code=exc.status)
        finally:
            if token is not None: current_user.reset(token)
        if path.startswith('/api/') or path in ('/', '/login'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.scheme == 'https': response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response
    return accounts
