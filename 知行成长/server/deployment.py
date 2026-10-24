"""Supported standalone web entrypoint; configuration errors never echo secrets."""
import argparse
import importlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    pass


def validate_config(env):
    errors, warnings = [], []
    raw = env.get('DATABASE_URL', '')
    try:
        url = urlsplit(raw)
        valid_db = url.scheme in ('postgres', 'postgresql') and bool(url.hostname) and bool(url.path.strip('/'))
    except ValueError:
        valid_db = False
    if not valid_db or any(v in raw for v in ('CHANGE_ME', 'REPLACE_WITH')):
        errors.append('DATABASE_URL')
    password = env.get('APP_PASSWORD', '')
    if len(password) < 24 or any(v in password for v in ('CHANGE_ME', 'REPLACE_WITH')):
        errors.append('APP_PASSWORD')
    if not re.fullmatch(r'[a-zA-Z0-9_\-]{3,32}', env.get('APP_USERNAME', 'owner')):
        errors.append('APP_USERNAME')
    from cryptography.fernet import Fernet
    try:
        Fernet(env.get('ACCOUNT_ENCRYPTION_KEY', '').encode())
    except (ValueError, TypeError):
        errors.append('ACCOUNT_ENCRYPTION_KEY')
    learn=env.get('LEARN_ROOT','')
    if not learn or not Path(learn).is_absolute() or 'REPLACE_WITH' in learn:
        errors.append('LEARN_ROOT (use a prepared teaching directory)')
    if env.get('PLAN_CONTENT_BACKEND') != 'github':
        errors.append('PLAN_CONTENT_BACKEND (standalone requires github)')
    if env.get('WEB_CONCURRENCY', '1') != '1':
        errors.append('WEB_CONCURRENCY (only one worker is supported)')
    if not env.get('GITHUB_CONTENT_REPO') or not env.get('GITHUB_CONTENT_TOKEN'):
        warnings.append('github_content_unconfigured')
    if env.get('GROW_SCHEDULED_READING_ENABLED', '0') not in ('0', '1'):
        errors.append('GROW_SCHEDULED_READING_ENABLED')
    if env.get('GROW_SCHEDULED_READING_ENABLED') == '1':
        from reading.scheduled import configuration
        if not configuration(env):
            errors.append('GROW_PUBLIC_URL / GROW_SCHEDULE_REPOSITORY / GROW_SCHEDULE_REPOSITORY_ID / GROW_SCHEDULE_REF')
    if errors:
        raise ConfigurationError('配置未通过，请核对：' + ', '.join(errors))
    return {'ok': True, 'warnings': warnings, 'workers': 1, 'action_owner': 'grow'}


def preflight(env=None, database=True):
    env = os.environ if env is None else env
    if sys.version_info < (3, 11):
        raise ConfigurationError('需要 Python 3.11 或更新版本。')
    report = validate_config(env)
    modules = ('fastapi', 'uvicorn', 'psycopg2', 'httpx', 'pydantic', 'jwt',
               'cryptography', 'trafilatura', 'pypdf', 'fontTools', 'multipart')
    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError:
            raise ConfigurationError('缺少运行依赖：' + module + '；请安装根 requirements.lock。') from None
    runtime = Path(env.get('RUNTIME_ROOT', Path(__file__).parent / 'runtime'))
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        import tempfile
        with tempfile.TemporaryFile(dir=runtime) as probe:
            probe.write(b'grow-preflight')
    except OSError:
        raise ConfigurationError('RUNTIME_ROOT 不可写，请核对目录权限。') from None
    materials=Path(env['LEARN_ROOT'])
    if not materials.is_dir():raise ConfigurationError('LEARN_ROOT 不存在，请先用 prepare_materials.py 导出正式教材到新目录。')
    if any(materials.glob('*/学习记录.md')) or (materials/'执行复盘').exists():
        report['warnings'].append('legacy_materials_root_owner_may_inherit_old_progress')
    if database:
        import psycopg2
        try:
            with psycopg2.connect(env['DATABASE_URL'], connect_timeout=5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1, has_database_privilege(current_database(),'CREATE')")
                    if not cursor.fetchone()[1]:
                        raise ConfigurationError('DATABASE_URL 角色缺少 CREATE SCHEMA 所需的数据库 CREATE 权限。')
        except psycopg2.Error:
            raise ConfigurationError('DATABASE_URL 连接检查失败，请核对地址、认证、TLS和数据库权限。') from None
    report['database_checked'] = database
    return report


def main():
    from run_local import load_environment
    load_environment(Path(__file__).resolve().parent)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'serve'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8756')))
    args = parser.parse_args()
    try:
        report = preflight()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report), flush=True)
    if args.command == 'serve':
        import uvicorn
        uvicorn.run('app:app', host=args.host, port=args.port, workers=1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
