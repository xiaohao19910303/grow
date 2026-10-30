"""Production login/settings and canonical web sessions against disposable real Zook HTTP."""
from run_isolated_checks import setup_isolation
if __name__ == '__main__':
    audit,runtime,_=setup_isolation();fixture=None
    try:
        import json,signal,socket,os
        from pathlib import Path
        import uvicorn
        from fastapi.responses import HTMLResponse
        from fastapi import Request
        from fastapi.staticfiles import StaticFiles
        from test_zook_web_http import CanonicalWebHTTPTests
        fixture=CanonicalWebHTTPTests();fixture.setUp();app=fixture.f.app
        _,lesson=fixture.f.prepare_practice()
        static=Path(__file__).resolve().parents[1]/'static'
        app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return HTMLResponse((static/'index.html').read_text())
        legacy=dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='fixture')
        @app.get('/api/data')
        def data():return legacy
        @app.put('/api/data')
        async def save_data(request:Request):
            legacy.update(await request.json());legacy['_revision']='fixture-saved'
            return {'ok':True,'state':legacy}
        @app.get('/api/{rest:path}')
        def empty(rest:str):return dict(invitations=[],modules=[],lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],legacy=[],drafts=[])
        sock=socket.socket();sock.bind(('127.0.0.1',0));server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        signal.signal(signal.SIGTERM,lambda *_:setattr(server,'should_exit',True))
        print(json.dumps({'url':'http://127.0.0.1:'+str(sock.getsockname()[1]),'lesson_id':lesson['id'],'account':fixture.f.owners[0]['account'],'grow_password':os.environ['APP_PASSWORD']}),flush=True)
        server.run(sockets=[sock])
    finally:
        if fixture:fixture.doCleanups()
        runtime.cleanup()
