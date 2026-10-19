"""Manual browser acceptance with real action/notes/material APIs in disposable PG."""
from pathlib import Path
import json
import asyncio
from unittest.mock import patch
import signal
import socket

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from test_study_materials import StudyMaterialTests
from study_materials import register as materials
from study_notes import register as notes
from action_plans import register as actions


def main():
    fixture = StudyMaterialTests()
    fixture.setUp()
    async def fixture_summary(snapshot, config):
        await asyncio.sleep(2)
        stats=snapshot['stats']
        return f"进展总结：已记录 {stats['minutes']} 分钟，{stats['completed']} 次达标。\n阻碍与不确定性：记录有限，不能推断刷视频时长。\n下阶段建议：晚饭后先读 5 分钟；将手机放远；周末再复盘。\n（隔离验收模型返回）"
    model=patch('action_reviews.generate_text',fixture_summary);model.start()
    try:
        (fixture.root / '结构化表达/每日练习/Day 001.md').write_text('# 结论先行\n\n## 练习：改写工作建议\n\n先给结论，再补充事实和例子。\n\n## 反思\n\n今天有什么收获？')
        app = FastAPI()
        actions(app);materials(app, fixture.root);notes(app)
        static = Path(__file__).resolve().parents[1] / 'static'
        app.mount('/static', StaticFiles(directory=static))
        @app.get('/')
        def index():return FileResponse(static / 'index.html')
        @app.get('/api/auth/me')
        def identity():return {'user': {'id': 'action-plans-fixture', 'username': '行动计划隔离验证', 'is_owner': True}}
        @app.get('/api/data')
        def data():return dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
        @app.get('/api/{rest:path}')
        def empty(rest: str):return dict(invitations=[], modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])
        sock = socket.socket();sock.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        signal.signal(signal.SIGTERM, lambda *_:setattr(server, 'should_exit', True))
        print(json.dumps({'url': 'http://127.0.0.1:'+str(sock.getsockname()[1])}), flush=True)
        server.run(sockets=[sock])
    finally:
        model.stop()
        fixture.doCleanups()


if __name__ == '__main__':main()
