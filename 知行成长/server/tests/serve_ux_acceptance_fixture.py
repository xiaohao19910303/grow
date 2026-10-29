"""Real UX acceptance APIs with synthetic content and disposable localhost PG.

TEST_POSTGRES_DSN='host=127.0.0.1 port=55446 user=grow_audit dbname=postgres' \
PYTHONPATH=知行成长/server:知行成长/server/tests 知行成长/.venv/bin/python -B 知行成长/server/tests/serve_ux_acceptance_fixture.py
"""
import ast
import asyncio
import importlib
import json
from pathlib import Path
import signal
import socket
from datetime import date, timedelta
from unittest.mock import patch

from run_isolated_checks import setup_isolation


def main():
    stats, runtime, server = setup_isolation()
    from test_legacy_cloud_api import CloudHTTPFixture
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn, db, httpx
    from legacy_state import load_state, save_state, patch_state
    from action_plans import register as actions
    from study_materials import initialize, register as materials
    from study_notes import register as notes
    from learning_checkins import read_checkins
    from plans.github import GitHubContent
    from plans.github_store import GitHubPlans

    fixture = CloudHTTPFixture(); fixture.setUp()
    try:
        app = fixture.app
        from tenancy import current_user
        @app.middleware('http')
        async def identity_context(request, call_next):
            token = current_user.set({'id': 'ux-acceptance', 'username': '隔离体验验收', 'is_owner': True})
            try: return await call_next(request)
            finally: current_user.reset(token)
        source = ast.parse((server / 'app.py').read_text())
        assignments = {target.id: node.value for node in source.body if isinstance(node, ast.Assign)
                       for target in node.targets if isinstance(target, ast.Name)}
        with db.connect() as conn:
            conn.executescript(ast.literal_eval(assignments['SCHEMA']))
            for module in ast.literal_eval(assignments['DEFAULT_MODULES']):
                conn.execute('INSERT INTO modules(id,name,color,ord) VALUES (?,?,?,?)',
                             (module['id'], module['name'], module['color'], module['order']))
        actions(app); initialize(); materials(app, fixture.root); notes(app)
        for name, folder in [('英文阅读', '每日文章'), ('结构化表达', '每日练习')]:
            directory = fixture.root / name / folder; directory.mkdir(parents=True, exist_ok=True)
            (directory / 'Day 001.md').write_text('# 验收课程：区分事实与判断\n\n## 练习\n\n怎样区分观察和推断？')
            (directory / 'Day 002.md').write_text('# 验收课程：检查证据\n\n## 练习\n\n写下一个可验证的问题。')
        content = GitHubContent('owner/courses', 'main', 'TEST_ONLY', transport=httpx.MockTransport(fixture.repository))
        plan_store = GitHubPlans(fixture.root, Path(fixture.tmp.name) / 'runtime', content)
        with patch('plans.api.make_store', return_value=plan_store):
            importlib.import_module('plans.api').register(app, fixture.root, Path(fixture.tmp.name) / 'runtime')
        plan_store.initialize(); plan_store.startup_error = None
        for module in ('reflections', 'stocks', 'behavior', 'errors', 'predictions', 'behavior_report', 'knowledge'):
            store = importlib.import_module(module + '.api').register(app, fixture.root, Path(fixture.tmp.name) / 'runtime')
            if isinstance(store, tuple): store = store[0]
            if hasattr(store, 'initialize'): store.initialize()
            store.startup_error = None
        from search_api import register as search
        from timeline_api import register as timeline
        search(app, fixture.root); timeline(app, fixture.root)
        @app.get('/api/errors', include_in_schema=False)
        def errors_without_slash():
            # Same endpoint as the framework's normal / -> redirect; no catch-all.
            from fastapi.responses import RedirectResponse
            return RedirectResponse('/api/errors/', status_code=307)
        @app.get('/api/data')
        def data(): return load_state(db.connect)
        @app.put('/api/data')
        async def put_data(request: Request):
            return save_state(db.connect, await request.json(), require_revision=True)
        @app.patch('/api/data')
        async def patch_data(request: Request):
            return await asyncio.to_thread(patch_state, db.connect, await request.json())
        @app.get('/api/learning-checkins')
        def checkins():
            with db.connect() as conn: return read_checkins(conn)
        context = {'date': date, 'timedelta': timedelta, 'get_conn': db.connect}
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('_ds', 'current_streak', 'build_report')]
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'actual-report-functions', 'exec'), context)
        @app.get('/api/report')
        def report(range: str = 'week'): return context['build_report'](7 if range == 'week' else 30)
        @app.get('/api/knowledge')
        def knowledge():
            with db.connect() as conn: return [dict(row) for row in conn.execute('SELECT * FROM knowledge')]
        @app.get('/api/auth/me')
        def identity(): return {'user': {'id': 'ux-acceptance', 'username': '隔离体验验收', 'is_owner': True}}
        @app.get('/api/account/github')
        def storage(): return {'mode': 'default', 'repository': 'audit/synthetic', 'branch': 'main', 'has_token': True}
        @app.get('/api/account/invitations')
        def invitations(): return {'invitations': []}
        @app.get('/')
        def index(): return FileResponse(server / 'static/index.html')
        app.mount('/static', StaticFiles(directory=server / 'static'))
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        service = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        signal.signal(signal.SIGTERM, lambda *_: setattr(service, 'should_exit', True))
        print(json.dumps({'url': 'http://127.0.0.1:' + str(sock.getsockname()[1]), 'article': fixture.aid}), flush=True)
        service.run(sockets=[sock])
    finally:
        fixture.doCleanups(); runtime.cleanup()
        assert not any(stats[key] for key in ('blocked_workspace_writes', 'blocked_real_database_access', 'blocked_network_access')), stats


if __name__ == '__main__': main()
