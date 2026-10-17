"""A narrowly scoped GitHub OIDC trigger for sleeping cloud services."""
from datetime import datetime
from zoneinfo import ZoneInfo

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

PATH = '/api/reading/scheduled-run'
AUDIENCE = 'https://zhixingchengzhang.onrender.com' + PATH
ISSUER = 'https://token.actions.githubusercontent.com'
REPOSITORY = 'xiaohao19910303/grow'
REPOSITORY_ID = '1415242621'
WORKFLOW = REPOSITORY + '/.github/workflows/daily-reading.yml@refs/heads/main'
jwks = jwt.PyJWKClient(ISSUER + '/.well-known/jwks', timeout=10)


def authorized(request):
    if request.url.path != PATH or request.method not in ('GET', 'POST'):return False
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 16000:return False
    try:
        if jwt.get_unverified_header(token).get('alg') != 'RS256':return False
        key = jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=ISSUER, audience=AUDIENCE,
                            options={'require':['exp','iat','nbf','sub','repository_id','workflow_ref','ref','event_name']})
        return (claims['repository_id'] == REPOSITORY_ID and claims.get('repository') == REPOSITORY
                and claims['workflow_ref'] == WORKFLOW and claims['ref'] == 'refs/heads/main'
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
