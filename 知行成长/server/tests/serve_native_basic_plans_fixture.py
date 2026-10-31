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
        os.environ['GROW_NATIVE_BASIC_PLANS_ENABLED']='1'
        assert fixture.link().status_code==200
        from fastapi.responses import RedirectResponse
        @app.get('/static/__qa-session')
        def qa_session():
            response=RedirectResponse('/native-plans',status_code=303)
            for cookie in fixture.client.cookies.jar:response.set_cookie(cookie.name,cookie.value,httponly=True,samesite='lax')
            return response
        import httpx
        import native_basic_plans
        from copilot.core import fail
        loss={'next':False}
        send=native_basic_plans.upstream
        def observed(*args,**kwargs):
            result=send(*args,**kwargs)
            if loss['next'] and len(args)>1 and args[1] in ('POST','PATCH'):
                loss['next']=False
                fail('synthetic_lost_response','Synthetic response lost after target commit',503)
            return result
        native_basic_plans.upstream=observed
        @app.get('/static/__qa/drop-next')
        def drop_next():loss['next']=True;return {'ready':True}
        @app.get('/static/__qa/state')
        def qa_state():
            h={'Authorization':'Bearer '+fixture.f.owners[0]['token'],'X-App-Id':'lighttick','X-LightTick-Task-Schema':'2'}
            result=httpx.get(fixture.f.url+'/api/v1/lighttick/manual-plans',headers=h)
            return result.json()['data']
        @app.get('/static/__qa/native-edit')
        def qa_native_edit():
            h={'Authorization':'Bearer '+fixture.f.owners[0]['token'],'X-App-Id':'lighttick','X-LightTick-Task-Schema':'2','Idempotency-Key':'browser-native-edit'}
            plans=httpx.get(fixture.f.url+'/api/v1/lighttick/manual-plans',headers=h).json()['data']['items']
            p=plans[0];body={**p['draft'],'base_version':p['version']};body['tasks'][0]['title']='Updated by native consumer'
            result=httpx.patch(fixture.f.url+'/api/v1/lighttick/manual-plans/'+p['id'],headers=h,json=body)
            return {'status':result.status_code,'plan':result.json().get('data')}
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
        print(json.dumps({'url':'http://127.0.0.1:'+str(sock.getsockname()[1]),'account':fixture.f.owners[0]['account']}),flush=True)
        server.run(sockets=[sock])
    finally:
        if fixture:fixture.doCleanups()
        runtime.cleanup()
