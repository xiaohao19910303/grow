"""Load local server configuration without executing shell text or rotating accounts."""
import argparse
import os
from pathlib import Path
import shlex

DEPLOYMENT_KEYS = {'DATABASE_URL', 'PLAN_CONTENT_BACKEND', 'GITHUB_CONTENT_REPO',
                   'GITHUB_CONTENT_BRANCH', 'GITHUB_CONTENT_TOKEN', 'ACCOUNT_ENCRYPTION_KEY'}


def read_env(path):
    if not path.is_file():
        return {}
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            raise ValueError(f'{path.name} 第 {number} 行配置格式无效。') from None
        if parts and parts[0] == 'export':
            parts = parts[1:]
        if not parts:
            continue
        if len(parts) != 1 or '=' not in parts[0]:
            raise ValueError(f'{path.name} 第 {number} 行配置格式无效。')
        key, value = parts[0].split('=', 1)
        values[key] = value
    return values


def load_environment(server):
    # Deployment helper files may also contain unrelated credentials, old AI
    # config and an obsolete bootstrap password. Only import server storage keys.
    shared = read_env(server.parents[1] / '.env.local')
    values = {key: value for key, value in shared.items() if key in DEPLOYMENT_KEYS}
    values.update(read_env(server / '.env'))
    for key, value in values.items():
        os.environ.setdefault(key, value)


if __name__ == '__main__':
    load_environment(Path(__file__).resolve().parent)
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8756')))
    args = parser.parse_args()
    import uvicorn
    uvicorn.run('app:app', host=args.host, port=args.port)
