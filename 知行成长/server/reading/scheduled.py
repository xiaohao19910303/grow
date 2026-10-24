"""A narrowly scoped GitHub OIDC trigger for sleeping cloud services."""
from datetime import datetime
import os
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

PATH = '/api/reading/scheduled-run'
ISSUER = 'https://token.actions.githubusercontent.com'
jwks = jwt.PyJWKClient(ISSUER + '/.well-known/jwks', timeout=10)


def configuration(env=None):
    env = os.environ if env is None else env
    if env.get('GROW_SCHEDULED_READING_ENABLED') != '1':return None
    base = env.get('GROW_PUBLIC_URL', '').rstrip('/')
    try:
        parsed = urlsplit(base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):return None
    except ValueError:return None
    repository = env.get('GROW_SCHEDULE_REPOSITORY', '')
    repository_id = env.get('GROW_SCHEDULE_REPOSITORY_ID', '')
    ref = env.get('GROW_SCHEDULE_REF', 'refs/heads/main')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):return None
    if not re.fullmatch(r'[0-9]+', repository_id):return None
    if not re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]+', ref) or '..' in ref:return None
    return {'audience':base + PATH, 'repository':repository, 'repository_id':repository_id,
            'ref':ref, 'workflow':repository + '/.github/workflows/daily-reading.yml@' + ref}


def authorized(request):
    configured = configuration()
    if not configured:return False
    if request.url.path != PATH or request.method not in ('GET', 'POST'):return False
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 16000:return False
    try:
        if jwt.get_unverified_header(token).get('alg') != 'RS256':return False
        key = jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=ISSUER, audience=configured['audience'],
                            options={'require':['exp','iat','nbf','sub','repository_id','workflow_ref','ref','event_name']})
        return (claims['repository_id'] == configured['repository_id'] and claims.get('repository') == configured['repository']
                and claims['workflow_ref'] == configured['workflow'] and claims['ref'] == configured['ref']
                and claims['event_name'] in ('schedule', 'workflow_dispatch', 'push'))
    except (jwt.PyJWTError, OSError, ValueError):
        return False


def register(router, store, service):
    @router.api_route('/scheduled-run', methods=['GET', 'POST'])
    async def scheduled_run(request: Request):
        from cloud_auth import guard
        from tenancy import current_user
        user = current_user.get()
        # The owner can also inspect/retry using normal site authentication.
        if user and not user['is_owner']:
            return JSONResponse({'message':'仅原管理账号可以触发平台定时搜集。'},status_code=403)
        if not user and await run_in_threadpool(guard,request) is not None:
            return JSONResponse({'message': '定时搜集凭证无效。'}, status_code=403)
        date = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        if not configuration():
            return {'date':date, 'state':'disabled', 'saved_count':0}
        prefs = store.prefs()
        if not prefs['enabled']:
            return {'date': date, 'state': 'paused', 'saved_count': 0}
        if request.method == 'POST':
            service.daily_tick()
        jobs = sorted((j for j in store.jobs() if j.get('daily') and j['date'] == date),
                      key=lambda j: j['created_at'], reverse=True)
        if jobs:
            job = jobs[0]
            return {'date': date, 'state': job['state'], 'job_id': job['id'],
                    'saved_count': len(job.get('saved_ids', [])), 'error': job.get('error')}
        return {'date': date, 'state': 'scheduled', 'saved_count': 0}
