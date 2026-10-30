"""Explicit Grow/LightTick association and server-side canonical Token sessions."""
from contextvars import ContextVar
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from copilot.core import fail
from tenancy import current_user

COOKIE = 'grow_zook_session'
active = ContextVar('grow_zook_web_session', default=None)
LIFETIME = 7 * 86400


def enabled(): return os.getenv('GROW_ZOOK_WEB_AUTH_ENABLED') == '1'


def assert_target(target):
    user = current_user.get() or {}
    expected = user.get('zook_target_user_id')
    if enabled() and expected and target != expected:
        fail('zook_binding_mismatch', '接管目标必须与已确认的统一账号一致，请核对原账号。', 409)


def base_url():
    value = os.getenv('LIGHTTICK_BRIDGE_URL', '').rstrip('/')
    try:
        p = urlsplit(value)
        valid = p.hostname and not (p.username or p.password or p.query or p.fragment) and p.path in ('', '/')
        valid = valid and (p.scheme == 'https' or p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost'))
    except ValueError: valid = False
    if not valid: fail('zook_unavailable', '统一账号服务尚未配置。', 503)
    return value


def upstream(path, method='GET', body=None, token=None, headers=None, query=None):
    h = {'X-App-Id': 'lighttick', **(headers or {})}
    if token: h['Authorization'] = 'Bearer ' + token
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            r = client.request(method, base_url() + path, json=body, params=query, headers=h)
        value = r.json()
    except (httpx.HTTPError, ValueError): fail('zook_unavailable', '账号服务连接未确认，请稍后重试。', 503)
    if not isinstance(value, dict): fail('zook_unavailable', '账号服务响应无效。', 503)
    if r.status_code >= 400:
        fail(str(value.get('code', 'zook_rejected')), str(value.get('message', '账号请求未完成。'))[:200], r.status_code)
    if not 200 <= r.status_code < 300: fail('zook_unavailable', '账号服务拒绝了当前连接。', 503)
    return value.get('data')


def registered(token):
    value = upstream('/api/v1/lighttick/account/session', token=token)
    if not isinstance(value, dict) or value.get('app_id') != 'lighttick' or value.get('account_kind') != 'registered' or value.get('membership_status') != 'ACTIVE':
        fail('zook_registered_required', '请使用正式LightTick账号。', 403)
    return value['user_id']


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256, repr=False)
    consent: bool = Field(default=False, strict=True)


class Sessions:
    def __init__(self, accounts): self.accounts = accounts

    def acquire_identity(self, user):
        """Held across the whole association/handoff request, before tenant writer locks."""
        from psycopg2 import DatabaseError
        import sys
        manager = self.accounts.conn(); c = manager.__enter__()
        try:
            c.execute("SET LOCAL lock_timeout='10s'")
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))', ('grow-identity:'+self.accounts.schema+':'+user['id'],))
            return manager
        except DatabaseError:
            manager.__exit__(*sys.exc_info())
            fail('zook_identity_busy', '账号关联或接管正在处理中，请保留当前输入后重试。', 503)

    def initialize(self):
        with self.accounts.conn() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS auth_zook_links (
              user_id TEXT PRIMARY KEY REFERENCES auth_users(id), target_user_id TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_zook_sessions (
              digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES auth_users(id),
              target_user_id TEXT NOT NULL, encrypted TEXT NOT NULL, expires_at BIGINT NOT NULL);
            CREATE INDEX IF NOT EXISTS auth_zook_session_user ON auth_zook_sessions(user_id);
            ''')

    def encrypt(self, value):
        from accounts import cipher
        return cipher().encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        from accounts import cipher
        from cryptography.fernet import InvalidToken
        try: return json.loads(cipher().decrypt(value.encode()))
        except (InvalidToken, ValueError): fail('zook_session_invalid', '统一会话无法恢复，请重新登录。', 401)

    def association(self, user_id):
        with self.accounts.conn() as c:
            row = c.execute('SELECT target_user_id FROM auth_zook_links WHERE user_id=?', (user_id,)).fetchone()
        return row[0] if row else None

    def login(self, body):
        if not enabled(): fail('zook_disabled', '统一网页登录尚未启用。', 503)
        value = upstream('/api/v1/auth/login', 'POST', {'appId': 'lighttick', 'clientType': 'app', 'account': body.account, 'password': body.password})
        if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in ('accessToken', 'refreshToken')):
            fail('zook_unavailable', '账号服务未提供可恢复会话。', 503)
        try:
            target = registered(value['accessToken'])
        except Exception:
            self.revoke_upstream(value)
            raise
        value['_origin'] = base_url()
        return target, value

    def refresh(self, value, c=None, digest=None):
        updated = upstream('/api/v1/auth/refresh', 'POST', {'appId': 'lighttick', 'clientType': 'app', 'refreshToken': value['refreshToken']})
        if not isinstance(updated, dict) or not all(isinstance(updated.get(k), str) and updated[k] for k in ('accessToken', 'refreshToken')):
            fail('zook_unavailable', '续期结果无法恢复，请重新登录。', 503)
        updated['_origin'] = base_url()
        if c is not None:
            c.execute('UPDATE auth_zook_sessions SET encrypted=? WHERE digest=?', (self.encrypt(updated), digest))
            # The upstream rotation cannot roll back. Persist it BEFORE any later network check.
            c._conn.commit()
        return updated

    def revoke_upstream(self, value, strict=False, c=None, digest=None):
        from copilot.core import Problem
        try:
            if value.get('_origin', base_url()) != base_url():
                if strict: fail('zook_session_invalid', '账号服务已变更，请恢复原服务后退出。', 503)
                return
            try: upstream('/api/v1/auth/logout', 'POST', {'appId': 'lighttick', 'refreshToken': value['refreshToken']}, value['accessToken'])
            except Problem as exc:
                if exc.status != 401: raise
                try: value = self.refresh(value, c, digest)
                except Problem as refresh_error:
                    if refresh_error.status == 401: return  # Already revoked.
                    raise
                upstream('/api/v1/auth/logout', 'POST', {'appId': 'lighttick', 'refreshToken': value['refreshToken']}, value['accessToken'])
        except Problem:
            if strict: raise

    def assert_bindings(self, user, target):
        from psycopg2 import sql
        # Only inspect the already authenticated Grow tenant; missing tables mean no existing binding.
        with self.accounts.conn() as c:
            for table in ('action_link_state', 'reflection_link_state', 'action_mobile_reading'):
                exists = c.execute('SELECT to_regclass(?)', (user['schema_name'] + '.' + table,)).fetchone()[0]
                if not exists: continue
                row = c._conn.cursor()
                row.execute(sql.SQL('SELECT data FROM {}.{} WHERE id=1').format(sql.Identifier(user['schema_name']), sql.Identifier(table)))
                saved = row.fetchone()
                link = json.loads(saved[0]) if saved else {}
                if table == 'action_mobile_reading': link = link.get('reading_binding', {})
                if link.get('target_user_id') and link['target_user_id'] != target:
                    fail('zook_binding_mismatch', '当前Grow数据已关联其他LightTick账号，请核对原账号。', 409)

    def issue(self, user, target, value, request):
        handle = secrets.token_urlsafe(32)
        with self.accounts.conn() as c:
            c.execute('DELETE FROM auth_zook_sessions WHERE expires_at<?', (int(time.time()),))
            c.execute('INSERT INTO auth_zook_sessions VALUES (?,?,?,?,?)',
                      (hashlib.sha256(handle.encode()).hexdigest(), user['id'], target, self.encrypt(value), int(time.time()) + LIFETIME))
        from accounts import public_user
        response = JSONResponse({'user': public_user(user), 'auth_mode': 'zook'})
        response.set_cookie(COOKIE, handle, max_age=LIFETIME, httponly=True, secure=request.url.scheme == 'https' or os.getenv('CLOUD_DEPLOY') == '1', samesite='lax')
        return response

    def resolve(self, handle):
        if not enabled() or not handle or len(handle) > 128: fail('zook_session_invalid', '请重新登录LightTick账号。', 401)
        digest = hashlib.sha256(handle.encode()).hexdigest()
        with self.accounts.conn() as c:
            row = c.execute('SELECT * FROM auth_zook_sessions WHERE digest=? AND expires_at>? FOR UPDATE', (digest, int(time.time()))).fetchone()
            if not row: fail('zook_session_invalid', '统一会话已过期，请重新登录。', 401)
            row = dict(row); value = self.decrypt(row['encrypted'])
            if value.get('_origin') != base_url(): fail('zook_session_invalid', '账号服务已变更，请重新登录。', 401)
            # Resolve immutable local identity before potentially rotating a remote refresh token.
            link = c.execute('SELECT target_user_id FROM auth_zook_links WHERE user_id=?', (row['user_id'],)).fetchone()
            user = c.execute('SELECT * FROM auth_users WHERE id=?', (row['user_id'],)).fetchone()
            if not user or not link or link[0] != row['target_user_id']: fail('zook_identity_changed', '账号关联已变化，请重新验证。', 401)
            from copilot.core import Problem
            try: target = registered(value['accessToken'])
            except Problem as exc:
                if exc.status != 401: raise
                value = self.refresh(value, c, digest)
                target = registered(value['accessToken'])
            if target != row['target_user_id']: fail('zook_identity_changed', '账号关联已变化，请重新验证。', 401)
        self.assert_bindings(dict(user), target)
        return dict(user), {'target': target, 'token': value['accessToken'], 'sessions': self, 'handle': handle}

    def logout(self, handle):
        if not handle or len(handle) > 128: return
        digest = hashlib.sha256(handle.encode()).hexdigest()
        with self.accounts.conn() as c:
            row = c.execute('SELECT encrypted FROM auth_zook_sessions WHERE digest=? FOR UPDATE', (digest,)).fetchone()
            if not row: return
            from copilot.core import Problem
            try: value = self.decrypt(row[0])
            except Problem:
                c.execute('DELETE FROM auth_zook_sessions WHERE digest=?', (digest,)); return
            self.revoke_upstream(value, strict=True, c=c, digest=digest)
            c.execute('DELETE FROM auth_zook_sessions WHERE digest=?', (digest,))


def install(app, accounts):
    sessions = Sessions(accounts); app.state.zook_web_sessions = sessions
    router = APIRouter(prefix='/api/auth/zook')

    @router.get('/config')
    def config(): return {'enabled': enabled()}

    @router.get('/status')
    def status(): return {'enabled': enabled(), 'linked': bool(sessions.association(current_user.get()['id'])), 'auth_mode': 'zook' if active.get() else 'grow'}

    @router.post('/link')
    def link(body: Credentials, request: Request):
        if not body.consent: fail('consent_required', '请明确确认关联这两个账号；不会自动迁移历史。', 422)
        user = current_user.get(); accounts.throttle(request.client.host if request.client else '')
        target, value = sessions.login(body)
        try:
            sessions.assert_bindings(user, target)
            with accounts.conn() as c:
                c.execute('SELECT id FROM auth_users WHERE id=? FOR UPDATE', (user['id'],)).fetchone()
                old = c.execute('SELECT target_user_id FROM auth_zook_links WHERE user_id=?', (user['id'],)).fetchone()
                other = c.execute('SELECT user_id FROM auth_zook_links WHERE target_user_id=?', (target,)).fetchone()
                if (old and old[0] != target) or (other and other[0] != user['id']): fail('zook_link_conflict', '身份已关联，请使用原账号；不会合并两个空间。', 409)
                from psycopg2 import IntegrityError
                try:
                    c.execute('INSERT INTO auth_zook_links VALUES (?,?) ON CONFLICT(user_id) DO NOTHING', (user['id'], target))
                except IntegrityError:
                    fail('zook_link_conflict', '该LightTick身份已关联其他空间，请核对原账号。', 409)
            return sessions.issue(user, target, value, request)
        except Exception:
            sessions.revoke_upstream(value)
            raise

    @router.post('/login')
    def login(body: Credentials, request: Request):
        accounts.throttle(request.client.host if request.client else '')
        target, value = sessions.login(body)
        with accounts.conn() as c:
            user = c.execute('SELECT u.* FROM auth_users u JOIN auth_zook_links l ON l.user_id=u.id WHERE l.target_user_id=?', (target,)).fetchone()
        if not user:
            sessions.revoke_upstream(value)
            fail('zook_link_required', '请先用原Grow账号登录，在设置中明确关联LightTick账号。', 409)
        sessions.logout(request.cookies.get(COOKIE, ''))
        try: return sessions.issue(dict(user), target, value, request)
        except Exception:
            sessions.revoke_upstream(value)
            raise

    app.include_router(router)
    return sessions
