"""Production page and real Grow/Zook APIs using isolated synthetic databases."""
from run_isolated_checks import setup_isolation

if __name__ == '__main__':
    audit, runtime, _ = setup_isolation()
    fixture = None
    try:
        import json
        import signal
        import socket
        from pathlib import Path
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        import uvicorn
        import study_materials
        import study_notes
        from tenancy import current_user
        from test_learning_practice_http import LearningPracticeHTTPTests
        fixture = LearningPracticeHTTPTests()
        fixture.setUp()
        app = fixture.app
        user = dict(current_user.get())
        faults = {'drop': False}

        @app.middleware('http')
        async def synthetic_identity_and_response_loss(request, call_next):
            token = current_user.set(user)
            try:
                dropping = faults['drop'] and request.method == 'POST' and request.url.path == '/api/action-plans/practices'
                if dropping:
                    faults['drop'] = False
                response = await call_next(request)
                if dropping and response.status_code == 200:
                    return JSONResponse({'detail': '保存已提交，隔离验收模拟响应丢失。'}, status_code=503)
                return response
            finally:
                current_user.reset(token)

        study_materials.register(app, fixture.root)
        study_notes.register(app)
        _, lesson = fixture.prepare_practice()
        static = Path(__file__).resolve().parents[1] / 'static'
        app.mount('/static', StaticFiles(directory=static))

        @app.get('/')
        def index():
            return HTMLResponse((static / 'index.html').read_text())

        @app.get('/api/auth/me')
        def who():
            return {'user': {**user, 'username': '学用隔离验收'}}

        @app.post('/fixture/drop-next')
        def drop():
            faults['drop'] = True
            return {'armed': True}

        @app.get('/api/data')
        def data():
            return dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')

        @app.get('/api/{rest:path}')
        def empty(rest: str):
            return dict(invitations=[], modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        signal.signal(signal.SIGTERM, lambda *_: setattr(server, 'should_exit', True))
        print(json.dumps({'url': 'http://127.0.0.1:' + str(sock.getsockname()[1]), 'lesson_id': lesson['id']}), flush=True)
        server.run(sockets=[sock])
    finally:
        if fixture:
            fixture.doCleanups()
        runtime.cleanup()
        if any(audit[k] for k in ('blocked_real_database_access', 'blocked_workspace_writes', 'blocked_network_access')):
            raise RuntimeError('Practice browser fixture isolation violation: ' + str(audit))
