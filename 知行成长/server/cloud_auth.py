"""Browser-native login for the single-user cloud pilot; secrets stay server-side."""
import base64
import binascii
import os
import secrets
from fastapi.responses import JSONResponse


def guard(request):
    if request.url.path == '/api/health': return None
    from reading.scheduled import authorized
    if authorized(request): return None
    password = os.getenv('APP_PASSWORD', '')
    if len(password) < 24:
        return JSONResponse({'message': '请在服务端配置至少 24 位的 APP_PASSWORD。'}, status_code=503)
    header = request.headers.get('authorization', '')
    try:
        scheme, value = header.split(' ', 1)
        if scheme.lower() != 'basic': raise ValueError()
        user, supplied = base64.b64decode(value, validate=True).decode('utf-8').split(':', 1)
    except (ValueError, UnicodeError, binascii.Error):
        user, supplied = '', ''
    expected_user = os.getenv('APP_USERNAME', 'owner')
    valid_user = secrets.compare_digest(user.encode(), expected_user.encode())
    valid_password = secrets.compare_digest(supplied.encode(), password.encode())
    if not (valid_user and valid_password):
        return JSONResponse({'message': '请登录个人学习平台。'}, status_code=401,
                            headers={'WWW-Authenticate': 'Basic realm="Learning", charset="UTF-8"',
                                     'Cache-Control': 'no-store'})
    return None
