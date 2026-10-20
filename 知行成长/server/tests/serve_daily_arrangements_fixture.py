"""Manual UI acceptance: disposable schema, real APIs, synthetic cloud content."""
from pathlib import Path
import json
import signal
import socket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from test_legacy_cloud_api import CloudHTTPFixture
from action_plans import register as actions
from study_materials import initialize,register as materials
from study_notes import register as notes


def main():
    fixture=CloudHTTPFixture();fixture.setUp()
    try:
        app=fixture.app;actions(app);initialize();materials(app,fixture.root);notes(app)
        article=fixture.reader.article(fixture.aid)
        article.update(title='证据与判断：从观察到结论',language='zh',content_version=2,import_method='paste',
            full_content='\n\n'.join(f'## 第 {n} 段：观察与推断\n\n这是隔离验收使用的合成文章。先记录可观察的事实，再区分自己的解释；提出可证伪的问题，保留不确定性。' for n in range(1,45)))
        fixture.reader.put('reading_records',fixture.aid,article)
        from tenancy import current_user
        @app.middleware('http')
        async def fixture_identity(request,call_next):
            token=current_user.set({'id':'agenda-fixture','username':'日程隔离验证','is_owner':True})
            try:return await call_next(request)
            finally:current_user.reset(token)
        for name,folder in [('英文阅读','每日文章'),('结构化表达','每日练习')]:
            directory=fixture.root/name/folder;directory.mkdir(parents=True,exist_ok=True)
            (directory/'Day 001.md').write_text('# 测试课程：从事实到结论\n\n## 练习\n先区分观察和推断，再提出可验证的问题。')
        static=Path(__file__).resolve().parents[1]/'static'
        app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return FileResponse(static/'index.html')
        @app.get('/api/auth/me')
        def identity():return {'user':{'id':'agenda-fixture','username':'日程隔离验证','is_owner':True}}
        @app.get('/api/data')
        def data():return dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='fixture')
        @app.get('/api/{rest:path}')
        def empty(rest:str):return dict(invitations=[],modules=[],lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],legacy=[],drafts=[])
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        signal.signal(signal.SIGTERM,lambda *_:setattr(server,'should_exit',True))
        print(json.dumps({'url':'http://127.0.0.1:'+str(sock.getsockname()[1]),'article':fixture.aid}),flush=True)
        server.run(sockets=[sock])
    finally:fixture.doCleanups()


if __name__=='__main__':main()
