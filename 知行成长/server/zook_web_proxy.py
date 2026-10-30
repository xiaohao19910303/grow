"""Bounded same-origin consumer of the one public LightTick contract."""
import re
from copilot.core import fail
from tenancy import current_user
from zook_web_auth import active, enabled, upstream


def session():
    value = active.get()
    if not value: fail('zook_login_required', '此数据已接管，请使用已关联的LightTick账号登录后继续。', 403)
    value['sessions'].assert_bindings(current_user.get(), value['target'])
    return value


def action(path, method, body, query):
    if method not in ('GET', 'POST'): fail('zook_proxy_forbidden', '请求方式不在接续范围。', 403)
    allowed_get = r'/(?:practices(?:/action-[a-zA-Z0-9-]+/source)?|records|reviews|learning-progress|requests/[a-zA-Z0-9_.:-]{8,160}|action-[a-zA-Z0-9-]+/calendar\.ics)'
    allowed_post = r'/(?:practices|schedules|reviews(?:/preview|/generate)?|action-[a-zA-Z0-9-]+/(?:operations|reminder-claim))'
    if not (path == '' or method == 'GET' and re.fullmatch(allowed_get, path) or method == 'POST' and re.fullmatch(allowed_post, path)):
        fail('zook_proxy_forbidden', '此路径不在网页接续范围。', 403)
    value = session()
    return upstream('/api/v1/lighttick/action-plans' + path, method, body if method == 'POST' else None, value['token'], {'X-Grow-Action-Schema': '2'}, query)


def records(kind, method='GET', **fields):
    value = session(); token = value['token']; prefix = '/api/v1/lighttick/records'
    identifier = fields.get('id', '')
    if identifier and not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', identifier): fail('zook_proxy_forbidden', '记录标识无效。', 422)
    if identifier.startswith('ref-'):
        from record_handoff import configuration, identity, digest
        config = configuration()
        if not config: fail('zook_proxy_unavailable', '记录来源配置不可用。', 503)
        identifier = 'grow-' + digest({'instance': config[2], 'subject': identity(), 'id': identifier})
    if method == 'GET':
        if kind == 'list': return upstream(prefix, token=token, query=fields.get('query', {}))
        if kind == 'export': return upstream(prefix + '/export', token=token)
        if kind == 'detail' and identifier: return upstream(prefix + '/' + identifier + '/history', token=token)
        if kind == 'attempt':
            # Existing read-only historical AI attempt lookup; the public owner export is authoritative.
            exported = upstream(prefix + '/export', token=token)
            for row in exported['records']:
                for attempt in (row.get('source_history') or {}).get('private_history', {}).get('attempts', []):
                    if attempt.get('id') == fields.get('id'): return attempt
            fail('not_found', '历史记录不存在。', 404)
    if method in ('PUT', 'POST') and kind in ('save', 'archive', 'restore') and identifier:
        suffix = '' if kind == 'save' else '/' + kind
        return upstream(prefix + '/' + identifier + suffix, method, fields.get('body', {}), token, {'Idempotency-Key': fields.get('key', '')})
    fail('zook_proxy_forbidden', '此记录操作不在网页接续范围。', 403)
