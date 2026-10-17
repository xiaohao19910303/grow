"""Request-scoped AI credentials. Never read a database or environment fallback."""
from urllib.parse import urlsplit
import sqlite3

from .core import fail

SERVER_AI_KEYS = ('api_base_url', 'api_key', 'model_name', 'price_version', 'input_price', 'output_price')


def remove_server_config(connection):
    """Drop only obsolete AI settings, without reading or returning their values."""
    if isinstance(connection, sqlite3.Connection):
        columns = {r[1] for r in connection.execute('PRAGMA table_info(copilot_settings)')}
    else:
        columns = {r[0] for r in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='copilot_settings'")}
    identity = 'key' if 'key' in columns else ('id' if 'id' in columns else None)
    if identity:
        connection.executemany(f'DELETE FROM copilot_settings WHERE {identity}=?', ((key,) for key in SERVER_AI_KEYS))


def config(value=None):
    value = value if isinstance(value, dict) else {}
    return {'url': value.get('api_base_url', ''), 'key': value.get('api_key', ''),
            'model': value.get('model_name', ''),
            'price_version': '', 'input_price': '', 'output_price': ''}


def require_config(value):
    if not isinstance(value, dict):
        fail('ai_config_required', '请先在设置中保存自己的 Base URL、API Key 和模型名称。', 422)
    for name, limit in (('api_base_url', 2048), ('api_key', 4096), ('model_name', 100)):
        item = value.get(name)
        if not isinstance(item, str) or not item.strip() or len(item) > limit or any(ord(c) < 32 for c in item):
            fail('ai_config_required', '请完整填写自己的 Base URL、API Key 和模型名称。', 422)
    clean = {name: value[name].strip() for name in ('api_base_url', 'api_key', 'model_name')}
    try:
        url = urlsplit(clean['api_base_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError()
        url.port
    except ValueError:
        fail('ai_config_invalid', 'Base URL 必须是无账号、查询参数和片段的 HTTPS 地址。', 422)
    endpoint = clean['api_base_url'].rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'
    clean['api_base_url'] = endpoint
    return config(clean)


def generation_config(value, transport=None):
    # Injected test transports do not need real credentials.
    return config() if value is None and transport is not None else require_config(value)
